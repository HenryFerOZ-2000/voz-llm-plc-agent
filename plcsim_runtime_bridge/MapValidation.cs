using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Threading;
using Siemens.Simatic.Simulation.Runtime;

namespace VozLlmPlcAgent.PlcsimRuntimeBridge
{
    // Separate DEVELOPMENT executable. It never changes the general RuntimeIO or
    // Oracle capabilities and cannot write output words or connect to hardware.
    internal static class MapValidation
    {
        private static byte[] Encode(int value,bool big)
        {
            if(value<Int16.MinValue || value>Int16.MaxValue)throw new InvalidOperationException("MAP_WORD_RANGE");
            byte hi=(byte)((value>>8)&255),lo=(byte)(value&255);
            return big?new[]{hi,lo}:new[]{lo,hi};
        }
        private static int Decode(byte[] bytes,bool big)
        {
            if(bytes.Length!=2)throw new InvalidOperationException("MAP_WORD_SIZE");
            return (short)(big?(bytes[0]<<8)|bytes[1]:(bytes[1]<<8)|bytes[0]);
        }
        private static void Target(string target,string purpose)
        {
            if(target!="PLCSIM_ADVANCED" || purpose!="MAP_ADAPTATION_DEVELOPMENT")
                throw new InvalidOperationException("MAP_VIRTUAL_TARGET_REQUIRED");
        }
        private static void Verify(Dictionary<string,Program.TagMeta> tags,Program.SignalRequest signal,bool write)
        {
            if(signal.DataType=="BOOL")
            {
                string detail;string error=Program.VerifySignal(tags,signal,write,out detail);
                if(error!=null)throw new InvalidOperationException(error+": "+detail);
                return;
            }
            Program.TagMeta tag;
            if(signal.DataType!="INT" || signal.Bit!=255 || (signal.Area!="Input" && signal.Area!="Output")
                || (write && signal.Area!="Input") || !tags.TryGetValue(signal.Name,out tag)
                || tag.Area!=signal.Area || tag.Offset!=signal.Offset || tag.Primitive!="Int16")
                throw new InvalidOperationException("MAP_WORD_BINDING_MISMATCH: "+signal.Name);
        }
        private static List<Dictionary<string,object>> Objects(object values)
        {return ((IEnumerable)values).Cast<object>().Select(v=>(Dictionary<string,object>)v).ToList();}

        private static Dictionary<string,object> SelfTest()
        {
            var checks=new Dictionary<string,object>();
            Action<string,Action,bool> check=(name,action,success)=>{bool passed=false;try{action();passed=success;}catch{passed=!success;}checks[name]=passed;};
            check("word_big",()=>{if(!Encode(12345,true).SequenceEqual(new byte[]{48,57}) || Decode(new byte[]{48,57},true)!=12345)throw new Exception();},true);
            check("word_little",()=>{if(!Encode(12345,false).SequenceEqual(new byte[]{57,48}) || Decode(new byte[]{57,48},false)!=12345)throw new Exception();},true);
            check("negative",()=>{if(Decode(Encode(-1,true),true)!=-1)throw new Exception();},true);
            var tags=new Dictionary<string,Program.TagMeta>{{"AI_Level",new Program.TagMeta{Name="AI_Level",Area="Input",Offset=64,Primitive="Int16"}},
                {"AO_Fill",new Program.TagMeta{Name="AO_Fill",Area="Output",Offset=64,Primitive="Int16"}}};
            Func<string,string,uint,Program.SignalRequest> word=(name,area,offset)=>new Program.SignalRequest{Name=name,Area=area,Offset=offset,Bit=255,DataType="INT"};
            check("word_input",()=>Verify(tags,word("AI_Level","Input",64),true),true);
            check("word_output_read",()=>Verify(tags,word("AO_Fill","Output",64),false),true);
            check("word_output_write_denied",()=>Verify(tags,word("AO_Fill","Output",64),true),false);
            check("word_type_mismatch",()=>{var s=word("AI_Level","Input",64);s.DataType="REAL";Verify(tags,s,true);},false);
            check("word_address_mismatch",()=>Verify(tags,word("AI_Level","Input",66),true),false);
            check("physical_target_denied",()=>Target("PHYSICAL","MAP_ADAPTATION_DEVELOPMENT"),false);
            check("wrong_purpose_denied",()=>Target("PLCSIM_ADVANCED","NORMAL"),false);
            check("valid_target",()=>Target("PLCSIM_ADVANCED","MAP_ADAPTATION_DEVELOPMENT"),true);
            return new Dictionary<string,object>{{"status",checks.Values.All(v=>(bool)v)?"PASSED":"FAILED"},{"checks",checks}};
        }

        private static Dictionary<string,object> Run(Dictionary<string,object> request)
        {
            Target(Program.GetString(request,"target_type",""),Program.GetString(request,"purpose",""));
            string name=Program.GetString(request,"instance_name","");
            var report=new Dictionary<string,object>{{"status","FAILED"},{"cleanup_verified",false}};
            var observations=new List<object>();report["observations"]=observations;
            IInstance instance=null;bool initialized=false;
            var originalBits=new Dictionary<string,bool>();var originalWords=new Dictionary<string,byte[]>();
            var signals=Objects(request["signals"]).Select(Program.ParseSignal).ToDictionary(s=>s.Name);
            var tags=new Dictionary<string,Program.TagMeta>();var endian=new Dictionary<string,bool>();
            Action guard=()=>{
                var infos=SimulationRuntimeManager.RegisteredInstanceInfo??new SInstanceInfo[0];
                if(instance==null || instance.OperatingState!=EOperatingState.Run
                    || Program.SelectInstances(infos.Select(i=>i.Name).ToList(),name).Count!=1)
                    throw new InvalidOperationException("MAP_EXACT_RUNNING_INSTANCE_REQUIRED");
            };
            Func<Program.SignalRequest,object> read=signal=>{
                guard();Verify(tags,signal,false);
                var area=signal.Area=="Input"?instance.InputArea:instance.OutputArea;
                if(signal.DataType=="BOOL")
                {
                    bool address=area.ReadBit(signal.Offset,signal.Bit),symbol=instance.ReadBool(signal.Name);
                    if(address!=symbol)throw new InvalidOperationException("MAP_BOOL_READBACK");
                    return symbol;
                }
                int value=instance.ReadInt16(signal.Name);byte[] bytes=area.ReadBytes(signal.Offset,2);
                bool big=true;
                if(endian.ContainsKey(signal.Name))big=endian[signal.Name];
                else if(Decode(bytes,true)!=value && Decode(bytes,false)==value)big=false;
                if(Decode(bytes,big)!=value)throw new InvalidOperationException("MAP_WORD_READBACK");
                return value;
            };
            Action<Program.SignalRequest,object> write=(signal,value)=>{
                guard();Verify(tags,signal,true);
                if(signal.DataType=="BOOL")
                {
                    if(!(value is bool))throw new InvalidOperationException("MAP_BOOL_VALUE_REQUIRED");
                    instance.InputArea.WriteBit(signal.Offset,signal.Bit,(bool)value);
                }
                else
                {
                    if(!(value is int) || !endian.ContainsKey(signal.Name))throw new InvalidOperationException("MAP_WORD_VALUE_REQUIRED");
                    instance.InputArea.WriteBytes(signal.Offset,Encode((int)value,endian[signal.Name]));
                }
                Thread.Sleep(10);
                if(Convert.ToDouble(read(signal))!=Convert.ToDouble(value))throw new InvalidOperationException("MAP_INPUT_READBACK");
            };
            try
            {
                if(!SimulationRuntimeManager.IsRuntimeManagerAvailable)throw new InvalidOperationException("MAP_RUNTIME_UNAVAILABLE");
                var infos=SimulationRuntimeManager.RegisteredInstanceInfo??new SInstanceInfo[0];
                var matches=Program.SelectInstances(infos.Select(i=>i.Name).ToList(),name);
                if(matches.Count!=1)throw new InvalidOperationException("MAP_EXACT_INSTANCE_REQUIRED");
                instance=SimulationRuntimeManager.CreateInterface(infos[matches[0]].Name);guard();
                instance.UpdateTagList(ETagListDetails.IODB,false);
                foreach(var tag in instance.TagInfos??new STagInfo[0])tags[tag.Name]=new Program.TagMeta{Name=tag.Name,
                    Area=tag.Area.ToString(),Offset=tag.Offset,Bit=tag.Bit,Primitive=tag.PrimitiveDataType.ToString()};
                foreach(var signal in signals.Values)
                {
                    Verify(tags,signal,signal.Area=="Input");
                    if(signal.Area!="Input")continue;
                    if(signal.DataType=="BOOL")originalBits[signal.Name]=instance.InputArea.ReadBit(signal.Offset,signal.Bit);
                    else originalWords[signal.Name]=instance.InputArea.ReadBytes(signal.Offset,2);
                }
                initialized=true;
                // Quiesce the freshly downloaded test program before probing word order.
                foreach(string control in new[]{"I_Stop_A","I_Emergency_A"})
                    if(signals.ContainsKey(control))write(signals[control],true);
                foreach(var signal in signals.Values.Where(s=>s.Area=="Input" && s.DataType=="INT"))
                {
                    guard();endian[signal.Name]=true;instance.InputArea.WriteBytes(signal.Offset,Encode(13824,true));Thread.Sleep(10);
                    if(instance.ReadInt16(signal.Name)!=13824)
                    {guard();endian[signal.Name]=false;instance.InputArea.WriteBytes(signal.Offset,Encode(13824,false));Thread.Sleep(10);}
                    if(Convert.ToInt32(read(signal))!=13824)throw new InvalidOperationException("MAP_WORD_PROBE_FAILED");
                    guard();instance.InputArea.WriteBytes(signal.Offset,originalWords[signal.Name]);
                }
                var steps=Objects(request["steps"]);
                if(steps.Count>100)throw new InvalidOperationException("MAP_STEP_LIMIT");
                foreach(var step in steps)
                {
                    guard();
                    foreach(var item in (Dictionary<string,object>)step["values"])write(signals[item.Key],item.Value);
                    int wait=Convert.ToInt32(step["settle_ms"]);
                    if(wait<0 || wait>1000)throw new InvalidOperationException("MAP_WAIT_LIMIT");
                    Thread.Sleep(wait);var actual=new Dictionary<string,object>();bool passed=true;
                    foreach(var expected in (Dictionary<string,object>)step["expected"])
                    {
                        actual[expected.Key]=read(signals[expected.Key]);
                        passed &= Math.Abs(Convert.ToDouble(actual[expected.Key])-Convert.ToDouble(expected.Value))<0.5;
                    }
                    observations.Add(new Dictionary<string,object>{{"id",step["id"]},{"actual",actual},{"expected",step["expected"]},{"passed",passed}});
                    if(!passed)throw new InvalidOperationException("MAP_BEHAVIOR_FAILED: "+step["id"]);
                }
                report["status"]="PASSED";
            }
            catch(Exception error){report["error"]=error.GetType().Name+": "+error.Message;}
            finally
            {
                if(initialized)
                {
                    try
                    {
                        if(signals.ContainsKey("I_Start_A"))write(signals["I_Start_A"],false);
                        if(signals.ContainsKey("I_Stop_A"))write(signals["I_Stop_A"],true);
                        Thread.Sleep(200);
                        foreach(var signal in signals.Values.Where(s=>s.Area=="Output"))
                            if(Convert.ToDouble(read(signal))!=0)throw new InvalidOperationException("MAP_OUTPUT_NOT_STOPPED");
                        foreach(var item in originalWords){guard();instance.InputArea.WriteBytes(signals[item.Key].Offset,item.Value);}
                        foreach(var item in originalBits)write(signals[item.Key],item.Value);
                        Thread.Sleep(200);
                        foreach(var item in originalWords)
                            if(!instance.InputArea.ReadBytes(signals[item.Key].Offset,2).SequenceEqual(item.Value))throw new InvalidOperationException("MAP_WORD_RESTORE");
                        foreach(var signal in signals.Values.Where(s=>s.Area=="Output"))
                            if(Convert.ToDouble(read(signal))!=0)throw new InvalidOperationException("MAP_OUTPUT_AFTER_RESTORE");
                        report["cleanup_verified"]=true;
                    }
                    catch(Exception error){report["status"]="FAILED";report["cleanup_error"]=error.Message;}
                }
                if(instance!=null)SimulationRuntimeManager.Shutdown();
            }
            return report;
        }
        private static int Main(string[] args)
        {
            AppDomain.CurrentDomain.AssemblyResolve+=(sender,eventArgs)=>{
                string path=Program.DefaultApiDll;
                return new AssemblyName(eventArgs.Name).Name==Path.GetFileNameWithoutExtension(path)?Assembly.LoadFrom(path):null;};
            var request=Program.Json.Deserialize<Dictionary<string,object>>(File.ReadAllText(args[0]));
            Dictionary<string,object> report;
            try{report=Program.GetString(request,"action","")=="self_test"?SelfTest():Run(request);}
            catch(Exception error){report=new Dictionary<string,object>{{"status","FAILED"},{"cleanup_verified",false},{"error",error.Message}};}
            File.WriteAllText(Convert.ToString(request["result_path"]),Program.Json.Serialize(report));
            return Convert.ToString(report["status"])=="PASSED"?0:1;
        }
    }
}
