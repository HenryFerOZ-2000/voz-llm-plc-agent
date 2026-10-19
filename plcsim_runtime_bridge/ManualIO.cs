using System;
using System.Collections;
using System.Collections.Generic;
using System.Linq;
using System.Threading;
using Siemens.Simatic.Simulation.Runtime;

namespace VozLlmPlcAgent.PlcsimRuntimeBridge
{
    // Manual bench controls deliberately do not extend the historical Oracle protocol.
    internal static class ManualIO
    {
        private static readonly Dictionary<string,string> Types=new Dictionary<string,string>{
            {"BOOL","Bool"},{"INT","Int16"},{"WORD","UInt16"},{"UINT","UInt16"},
            {"DINT","Int32"},{"DWORD","UInt32"},{"REAL","Float"}};

        internal static string Verify(Dictionary<string,Program.TagMeta> tags,Program.SignalRequest s)
        {
            Program.TagMeta t;
            if(!Types.ContainsKey(s.DataType) || (s.Area!="Input" && s.Area!="Output") ||
               (s.DataType=="BOOL" ? s.Bit>7 : s.Bit!=255))return "PLCSIM_SIGNAL_TYPE_UNSUPPORTED";
            if(!tags.TryGetValue(s.Name,out t) || t.Area!=s.Area || t.Offset!=s.Offset ||
               (s.DataType=="BOOL" && t.Bit!=s.Bit))return "PLCSIM_SIGNAL_NOT_IN_CURRENT_PROGRAM";
            if(t.Primitive!=Types[s.DataType])return "PLCSIM_SIGNAL_TYPE_UNSUPPORTED";
            return null;
        }

        internal static string WriteGuard(string target,string state,Program.SignalRequest s)
        {
            if(target!="PLCSIM_ADVANCED")return "PLCSIM_IO_WRITE_NOT_ALLOWED";
            if(s.Area=="Input" && state=="RUN" || s.Area=="Output" && state=="STOP")return null;
            return "PLCSIM_IO_CPU_STATE_REQUIRED";
        }

        internal static object Value(Program.SignalRequest s,object raw)
        {
            if(s.DataType=="BOOL")
            {
                if(!(raw is bool))throw new InvalidOperationException("PLCSIM_IO_VALUE_RANGE: BOOL required");
                return (bool)raw;
            }
            if(raw==null || raw is bool || raw is string)throw new InvalidOperationException("PLCSIM_IO_VALUE_RANGE: numeric value required");
            double n=Convert.ToDouble(raw);
            if(Double.IsNaN(n)||Double.IsInfinity(n))throw new InvalidOperationException("PLCSIM_IO_VALUE_RANGE: finite value required");
            if(s.DataType=="REAL")
            {
                if(n>Single.MaxValue||n< -Single.MaxValue)throw new InvalidOperationException("PLCSIM_IO_VALUE_RANGE: REAL overflow");
                return (float)n;
            }
            if(n!=Math.Truncate(n))throw new InvalidOperationException("PLCSIM_IO_VALUE_RANGE: integer required");
            switch(s.DataType)
            {
                case "INT":return checked((short)n);
                case "WORD":case "UINT":return checked((ushort)n);
                case "DINT":return checked((int)n);
                case "DWORD":return checked((uint)n);
                default:throw new InvalidOperationException("PLCSIM_SIGNAL_TYPE_UNSUPPORTED");
            }
        }

        private static object ReadTag(IInstance i,Program.SignalRequest s)
        {
            switch(s.DataType)
            {
                case "BOOL":return i.ReadBool(s.Name);
                case "INT":return i.ReadInt16(s.Name);
                case "WORD":case "UINT":return i.ReadUInt16(s.Name);
                case "DINT":return i.ReadInt32(s.Name);
                case "DWORD":return i.ReadUInt32(s.Name);
                case "REAL":return i.ReadFloat(s.Name);
                default:throw new InvalidOperationException("PLCSIM_SIGNAL_TYPE_UNSUPPORTED");
            }
        }

        private static double Decode(byte[] b,string type)
        {
            switch(type)
            {
                case "INT":return BitConverter.ToInt16(b,0);
                case "WORD":case "UINT":return BitConverter.ToUInt16(b,0);
                case "DINT":return BitConverter.ToInt32(b,0);
                case "DWORD":return BitConverter.ToUInt32(b,0);
                case "REAL":return BitConverter.ToSingle(b,0);
                default:throw new InvalidOperationException("PLCSIM_SIGNAL_TYPE_UNSUPPORTED");
            }
        }

        private static object Read(IInstance i,Program.SignalRequest s)
        {
            IIOArea area=s.Area=="Input"?i.InputArea:i.OutputArea;
            for(int attempt=0;attempt<5;attempt++)
            {
                object before=ReadTag(i,s);
                if(s.DataType=="BOOL")
                {
                    bool bit=area.ReadBit(s.Offset,s.Bit);
                    if(bit==Convert.ToBoolean(before) && bit==Convert.ToBoolean(ReadTag(i,s)))return bit;
                }
                else
                {
                    byte[] bytes=area.ReadBytes(s.Offset,(uint)(s.DataType=="INT"||s.DataType=="WORD"||s.DataType=="UINT"?2:4));
                    object after=ReadTag(i,s);
                    if(Convert.ToDouble(before)==Convert.ToDouble(after))
                    {
                        double n=Convert.ToDouble(after),a=Decode(bytes,s.DataType);
                        Array.Reverse(bytes);double b=Decode(bytes,s.DataType);
                        if(n==a||n==b)return after;
                    }
                }
                Thread.Sleep(2);
            }
            throw new InvalidOperationException("PLCSIM_IO_READBACK_MISMATCH: no coherent process-image and symbol read for "+s.Name);
        }

        private static void Write(IInstance i,Program.SignalRequest s,object v,string target)
        {
            string error=WriteGuard(target,i.OperatingState.ToString().ToUpperInvariant(),s);
            if(error!=null)throw new InvalidOperationException(error+": input requires RUN; manual output requires STOP");
            // Typed symbol writes only after exact name/area/address/IEC-type verification.
            // Readback independently verifies the process image, without guessing byte order.
            switch(s.DataType)
            {
                case "BOOL":i.WriteBool(s.Name,(bool)v);break;
                case "INT":i.WriteInt16(s.Name,(short)v);break;
                case "WORD":case "UINT":i.WriteUInt16(s.Name,(ushort)v);break;
                case "DINT":i.WriteInt32(s.Name,(int)v);break;
                case "DWORD":i.WriteUInt32(s.Name,(uint)v);break;
                case "REAL":i.WriteFloat(s.Name,(float)v);break;
            }
        }

        internal static Dictionary<string,object> Execute(Dictionary<string,object> request)
        {
            var report=Program.NewReport("PLCSIM_RUNTIME_ERROR","manual_io");
            report["reads"]=new List<object>();report["writes"]=new List<object>();
            string target=Program.GetString(request,"target_type","");
            IInstance instance=null;
            try
            {
                if(target!="PLCSIM_ADVANCED" || Program.GetString(request,"purpose","")!="MANUAL_IO")
                    throw new InvalidOperationException("PLCSIM_IO_WRITE_NOT_ALLOWED: explicit virtual manual session required");
                var infos=SimulationRuntimeManager.RegisteredInstanceInfo;
                var matches=Program.SelectInstanceIdentity(infos.Select(x=>x.Name).ToArray(),infos.Select(x=>(int)x.ID).ToArray(),
                    Program.GetString(request,"instance_name",""),request.ContainsKey("instance_id")?(int?)Convert.ToInt32(request["instance_id"]):null);
                if(matches.Count!=1)throw new InvalidOperationException("PLCSIM_INSTANCE_NOT_FOUND: unique selected identity required");
                instance=SimulationRuntimeManager.CreateInterface((int)infos[matches[0]].ID);
                report["instance_name"]=infos[matches[0]].Name;report["instance_id"]=(int)infos[matches[0]].ID;
                report["cpu_state"]=instance.OperatingState.ToString().ToUpperInvariant();
                instance.UpdateTagList(ETagListDetails.IODB,false);
                var tags=(instance.TagInfos??new STagInfo[0]).ToDictionary(t=>t.Name,t=>new Program.TagMeta{
                    Name=t.Name,Area=t.Area.ToString(),Offset=t.Offset,Bit=t.Bit,Primitive=t.PrimitiveDataType.ToString()});
                var s=Program.ParseSignal(request["signal"]);
                var expected=((IEnumerable)request["expected_signals"]).Cast<object>().Select(Program.ParseSignal).ToList();
                if(!expected.Any(e=>e.Name==s.Name && e.Area==s.Area && e.Offset==s.Offset && e.Bit==s.Bit && e.DataType==s.DataType))
                    throw new InvalidOperationException("PLCSIM_SIGNAL_NOT_IN_CURRENT_PROGRAM: signal outside downloaded bindings");
                foreach(var e in expected)
                {
                    string error=Verify(tags,e);
                    if(error!=null)throw new InvalidOperationException(error+": "+e.Name);
                }
                string op=Program.GetString(request,"operation","");
                if(op=="read")
                {
                    ((List<object>)report["reads"]).Add(new Dictionary<string,object>{{"name",s.Name},{"address",s.Address},
                        {"value",Read(instance,s)},{"timestamp",DateTime.Now.ToString("o")}});
                }
                else if(op=="write"||op=="restore")
                {
                    object value=Value(s,request["value"]),original=Read(instance,s);
                    try
                    {
                        Write(instance,s,value,target);
                        Thread.Sleep(Math.Max(0,Math.Min(1000,request.ContainsKey("settle_ms")?Convert.ToInt32(request["settle_ms"]):20)));
                        object actual=Read(instance,s);
                        bool match=Convert.ToDouble(value)==Convert.ToDouble(actual);
                        ((List<object>)report["writes"]).Add(new Dictionary<string,object>{{"name",s.Name},{"address",s.Address},
                            {"data_type",s.DataType},{"requested_value",value},{"actual_readback",actual},{"readback_tag",ReadTag(instance,s)},
                            {"match",match},{"readback_timestamp",DateTime.Now.ToString("o")}});
                        if(!match)throw new InvalidOperationException("PLCSIM_INPUT_READBACK_MISMATCH: "+s.Name);
                    }
                    catch
                    {
                        try {Write(instance,s,original,target);report["rollback_verified"]=Convert.ToDouble(Read(instance,s))==Convert.ToDouble(original);}
                        catch {report["rollback_verified"]=false;}
                        throw;
                    }
                }
                else throw new InvalidOperationException("PLCSIM_IO_WRITE_NOT_ALLOWED: unknown manual operation");
                report["status"]="PLCSIM_IO_PASSED";
            }
            catch(Exception error)
            {
                string code=error.Message.Split(':')[0];
                report["status"]=code.StartsWith("PLCSIM_")?code:"PLCSIM_RUNTIME_ERROR";
                Program.AddError(report,error.Message);
            }
            finally {try{if(instance!=null)instance.Dispose();}catch{}try{SimulationRuntimeManager.Shutdown();}catch{}}
            return report;
        }

        internal static Dictionary<string,object> SelfTest()
        {
            var checks=new List<object>();
            Action<string,bool> check=(name,passed)=>checks.Add(new Dictionary<string,object>{{"check",name},{"passed",passed}});
            var s=new Program.SignalRequest{Name="AI_Test",Area="Input",Offset=64,Bit=255,DataType="INT"};
            var tags=new Dictionary<string,Program.TagMeta>{{s.Name,new Program.TagMeta{Name=s.Name,Area=s.Area,Offset=64,Bit=0,Primitive="Int16"}}};
            check("word_exact_binding",Verify(tags,s)==null);
            s.Offset=4;check("different_address_denied",Verify(tags,s)!=null);s.Offset=64;
            check("physical_denied",WriteGuard("PHYSICAL_PLC","RUN",s)!=null);
            check("input_run",WriteGuard("PLCSIM_ADVANCED","RUN",s)==null);
            check("input_stop_denied",WriteGuard("PLCSIM_ADVANCED","STOP",s)!=null);
            s.Area="Output";check("output_run_denied",WriteGuard("PLCSIM_ADVANCED","RUN",s)!=null);
            check("output_stop",WriteGuard("PLCSIM_ADVANCED","STOP",s)==null);
            check("integer_preserved",Convert.ToInt32(Value(s,13824))==13824);
            bool denied=false;try{Value(s,true);}catch{denied=true;}check("bool_not_numeric",denied);
            denied=false;try{Value(s,40000);}catch{denied=true;}check("overflow_denied",denied);
            var report=Program.NewReport(checks.Cast<Dictionary<string,object>>().All(c=>(bool)c["passed"])?
                "PLCSIM_MANUAL_IO_SELF_TEST_PASSED":"PLCSIM_MANUAL_IO_SELF_TEST_FAILED","manual_io_self_test");
            report["checks"]=checks;return report;
        }
    }
}
