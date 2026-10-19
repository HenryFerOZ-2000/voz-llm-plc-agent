using System;
using System.Collections;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Runtime.CompilerServices;
using System.Text.RegularExpressions;
using System.Threading;
using System.Threading.Tasks;
using Siemens.Simatic.Simulation.Runtime;

namespace VozLlmPlcAgent.PlcsimRuntimeBridge
{
    // A plant provider owns ONE input connection. It observes, never writes, the output.
    internal sealed class PidPlantSession
    {
        private readonly Dictionary<string,object> request;
        private readonly Dictionary<string,object> manifest, bindings, input, output;
        private readonly string instanceName, db;
        private int? instanceId;
        private readonly int[] expectedSignature;
        private readonly double deadline;
        private readonly Stopwatch clock=Stopwatch.StartNew();
        private readonly Dictionary<string,Program.TagMeta> tags=new Dictionary<string,Program.TagMeta>(StringComparer.Ordinal);
        private readonly Dictionary<string,Program.SignalRequest> diagnostics=new Dictionary<string,Program.SignalRequest>();
        private readonly List<string> errors=new List<string>();
        private IInstance instance;
        private Program.SignalRequest measurement, quality, command, stop;
        private object original;
        private bool originalQuality, snapshotTaken, probePassed, bigEndian=true;
        private byte[] originalBytes;

        private PidPlantSession(Dictionary<string,object> header)
        {
            request=header;
            if(Program.GetString(header,"target_type","")!="PLCSIM_ADVANCED" ||
                Program.GetString(header,"purpose","")!="NATIVE_PID_PLANT_TEST" ||
                !header.ContainsKey("compiled_package_verified") || !Object.Equals(header["compiled_package_verified"],true))
                throw new InvalidOperationException("PID_PLANT_TARGET: explicit compiled PLCSIM package required");
            instanceName=Program.GetString(header,"instance_name","");
            instanceId=header.ContainsKey("instance_id")?(int?)Convert.ToInt32(header["instance_id"]):null;
            if(String.IsNullOrWhiteSpace(instanceName))throw new InvalidOperationException("PID_PLANT_TARGET: instance required");
            manifest=(Dictionary<string,object>)header["manifest"];
            bindings=(Dictionary<string,object>)header["bindings"];
            if(!Object.Equals(manifest["schema_version"],2) || Convert.ToString(manifest["owner"])!="VozLlmPlcAgent.NativePID.v2")
                throw new InvalidOperationException("PID_PLANT_PACKAGE: v2 required");
            var loops=Objects(manifest["loops"]);
            if(loops.Count!=1)throw new InvalidOperationException("PID_PLANT_PACKAGE: one loop required");
            input=(Dictionary<string,object>)loops[0]["input_binding"];
            output=(Dictionary<string,object>)loops[0]["output_binding"];
            ValidateBinding(input,"MEASUREMENT",manifest);
            ValidateBinding(output,"MANIPULATED",manifest);
            if(!Same(input,bindings["input_binding"]) || !Same(output,bindings["output_binding"]))
                throw new InvalidOperationException("PID_PLANT_BINDING: descriptors differ");
            db=Convert.ToString(((Dictionary<string,object>)loops[0]["symbols"])["db"]);
            if(!Regex.IsMatch(db,@"^DB_PID_[A-Za-z][A-Za-z0-9_]{0,39}$") || Convert.ToString(bindings["instance_db"])!=db)
                throw new InvalidOperationException("PID_PLANT_PACKAGE: controller DB mismatch");
            expectedSignature=((IEnumerable)bindings["build_signature"]).Cast<object>().Select(Convert.ToInt32).ToArray();
            if(expectedSignature.Length!=16 || expectedSignature.Any(n=>n<Int16.MinValue || n>Int16.MaxValue))
                throw new InvalidOperationException("PID_PLANT_PACKAGE: 16 signed Build words required");
            deadline=Convert.ToDouble(header["deadline_s"]);
            if(Double.IsNaN(deadline)||Double.IsInfinity(deadline)||deadline<1||deadline>3600)
                throw new InvalidOperationException("PID_PLANT_DEADLINE: invalid deadline");
        }

        private static List<Dictionary<string,object>> Objects(object raw)
        {
            return ((IEnumerable)raw).Cast<object>().Select(o=>(Dictionary<string,object>)o).ToList();
        }

        private static bool Same(object a,object b)
        {
            var x=a as Dictionary<string,object>;var y=b as Dictionary<string,object>;
            if(x!=null || y!=null)return x!=null && y!=null && x.Count==y.Count && x.All(p=>y.ContainsKey(p.Key)&&Same(p.Value,y[p.Key]));
            if(a is string || b is string || a is bool || b is bool || a==null || b==null)return Object.Equals(a,b);
            if(a is IEnumerable && b is IEnumerable)
            {
                var left=((IEnumerable)a).Cast<object>().ToArray();var right=((IEnumerable)b).Cast<object>().ToArray();
                return left.Length==right.Length && left.Select((v,i)=>Same(v,right[i])).All(v=>v);
            }
            return Convert.ToDouble(a)==Convert.ToDouble(b);
        }

        internal static void ValidateBinding(Dictionary<string,object> binding,string role,Dictionary<string,object> manifest)
        {
            var loop=Objects(manifest["loops"]).Single();
            string key=role=="MEASUREMENT"?"input_binding":"output_binding";
            if((role!="MEASUREMENT" && role!="MANIPULATED") || !Same(binding,loop[key]) ||
                !Object.Equals(binding["permission"],true) || Convert.ToString(binding["role"])!=role)
                throw new InvalidOperationException("PID_PLANT_BINDING: undeclared connection");
            string repr=Convert.ToString(binding["representation"]);
            if(repr=="HARDWARE_RAW")
            {
                string pattern=role=="MEASUREMENT"?@"^%IW\d+$":@"^%QW\d+$";
                if(Convert.ToString(binding["data_type"])!="INT" || !Regex.IsMatch(Convert.ToString(binding["address"]),pattern))
                    throw new InvalidOperationException("PID_PLANT_BINDING: input/output word area mismatch");
            }
            else if(repr=="DB_ENGINEERING")
            {
                var storage=(Dictionary<string,object>)binding["storage"];
                if(Convert.ToString(storage["kind"])!="GENERATED_DB" || Convert.ToString(binding["data_type"])!="REAL")
                    throw new InvalidOperationException("PID_PLANT_BINDING: generated DB REAL required");
                var groups=Objects(manifest["process_dbs"]).Where(g=>Convert.ToString(g["db"])==Convert.ToString(storage["db"]) &&
                    Convert.ToString(g["owner"])=="VozLlmPlcAgent.NativePID.v2").ToList();
                if(groups.Count!=1)throw new InvalidOperationException("PID_PLANT_BINDING: foreign DB");
                var members=Objects(groups[0]["members"]);
                if(members.Count(m=>Convert.ToString(m["name"])==Convert.ToString(storage["member"]) && Convert.ToString(m["data_type"])=="REAL" && Convert.ToString(m["role"])==role)!=1)
                    throw new InvalidOperationException("PID_PLANT_BINDING: undeclared REAL member");
                if(role=="MEASUREMENT" && members.Count(m=>Convert.ToString(m["name"])==Convert.ToString(binding["validity_member"]) &&
                    Convert.ToString(m["data_type"])=="BOOL" && Convert.ToString(m["role"])=="QUALITY")!=1)
                    throw new InvalidOperationException("PID_PLANT_BINDING: undeclared quality member");
            }
            else throw new InvalidOperationException("PID_PLANT_BINDING: unsupported representation");
        }

        internal static void CheckIdentity(int[] expected,int[] actual,bool run,bool sameInstance)
        {
            if(!run || !sameInstance)throw new InvalidOperationException("PID_PLANT_TARGET: exact registered instance and RUN required");
            if(expected.Length!=16 || !expected.SequenceEqual(actual))throw new InvalidOperationException("PID_PROGRAM_MISMATCH: loaded Build signature changed");
        }

        private void Guard()
        {
            var infos=SimulationRuntimeManager.RegisteredInstanceInfo??new SInstanceInfo[0];
            bool selected=Program.SelectInstanceIdentity(infos.Select(i=>i.Name).ToList(),infos.Select(i=>(int)i.ID).ToList(),instanceName,instanceId).Count==1
                && instance!=null && instance.ID==instanceId;
            bool run=instance!=null && instance.OperatingState==EOperatingState.Run;
            // The actual loaded values, never a cached UI/report flag, authorize each write.
            var actual=new int[16];
            if(run && selected)for(int i=0;i<16;i++)actual[i]=(int)instance.ReadInt16(diagnostics["Build"+i.ToString("00")].ApiName);
            CheckIdentity(expectedSignature,actual,run,selected);
        }

        private Program.SignalRequest ResolveDb(string name,string member,string type)
        {
            var signal=new Program.SignalRequest{Db=name,Member=member,Name=name+"."+member,DataType=type};
            Program.TagMeta tag;string detail;
            string error=Program.ResolveRuntimeName(tags,signal,out tag,out detail);
            string primitive=type=="REAL"?"Float":type=="BOOL"?"Bool":type=="INT"?"Int16":"UInt32";
            if(error!=null || tag.Primitive!=primitive)throw new InvalidOperationException("PID_PLANT_TAG: "+detail+" expected "+primitive);
            return signal;
        }

        private Program.SignalRequest ResolveConnection(Dictionary<string,object> binding)
        {
            if(Convert.ToString(binding["representation"])=="DB_ENGINEERING")
            {
                var s=(Dictionary<string,object>)binding["storage"];
                return ResolveDb(Convert.ToString(s["db"]),Convert.ToString(s["member"]),"REAL");
            }
            string name=Convert.ToString(binding["name"]),address=Convert.ToString(binding["address"]);
            string area=Convert.ToString(binding["role"])=="MEASUREMENT"?"Input":"Output";
            uint offset=UInt32.Parse(address.Substring(3));Program.TagMeta tag;
            if(!tags.TryGetValue(name,out tag) || tag.Area!=area || tag.Offset!=offset || tag.Primitive!="Int16")
                throw new InvalidOperationException("PID_PLANT_TAG: word symbol/area/address/type mismatch "+name);
            return new Program.SignalRequest{Name=tag.Name,RuntimeName=tag.Name,Area=area,Offset=offset,DataType="INT"};
        }

        private object Read(Program.SignalRequest signal)
        {
            if(signal.DataType=="BOOL")return instance.ReadBool(signal.ApiName);
            if(signal.DataType=="REAL")return instance.ReadFloat(signal.ApiName);
            if(signal.DataType=="DWORD")return instance.ReadUInt32(signal.ApiName);
            return (int)instance.ReadInt16(signal.ApiName);
        }

        private byte[] ReadWordBytes(Program.SignalRequest signal)
        {
            return (signal.Area=="Input"?instance.InputArea:instance.OutputArea).ReadBytes(signal.Offset,2);
        }

        private static int Decode(byte[] bytes,bool big)
        {
            if(bytes==null || bytes.Length!=2)throw new InvalidOperationException("PID_WORD_READ: expected two bytes");
            return (short)(big?(bytes[0]<<8)|bytes[1]:(bytes[1]<<8)|bytes[0]);
        }

        private int ReadWord(Program.SignalRequest signal)
        {
            // Symbolic and process-image reads are separate API calls. A cyclic
            // output may change between them; compare only a stable observation.
            string observation="";
            for(int attempt=0;attempt<5;attempt++)
            {
                int before=(int)Read(signal);byte[] bytes=ReadWordBytes(signal);
                int after=(int)Read(signal);
                observation="area="+signal.Area+", before="+before+", after="+after+", address="+Decode(bytes,bigEndian);
                if(before!=after){Thread.Sleep(2);continue;}
                if(!probePassed && Decode(bytes,true)!=after && Decode(bytes,false)==after)bigEndian=false;
                if(Decode(bytes,bigEndian)==after)return after;
                Thread.Sleep(2);
            }
            throw new InvalidOperationException("PID_WORD_READBACK: no coherent address/symbol observation; "+observation);
        }

        private void WriteRaw(int value)
        {
            Guard();
            if(value<Int16.MinValue || value>Int16.MaxValue || measurement.Area!="Input")
                throw new InvalidOperationException("PID_PLANT_WRITE: only declared input INT16 permitted");
            byte hi=(byte)((value>>8)&255),lo=(byte)(value&255);
            instance.InputArea.WriteBytes(measurement.Offset,bigEndian?new[]{hi,lo}:new[]{lo,hi});
        }

        private void WriteMeasurement(float value,bool valid)
        {
            if(!valid){Guard();instance.WriteBool(quality.ApiName,false);}
            Guard();instance.WriteFloat(measurement.ApiName,value);
            if(Math.Abs(instance.ReadFloat(measurement.ApiName)-value)>.001)
                throw new InvalidOperationException("PID_PLANT_READBACK: DB measurement differs");
            Guard();instance.WriteBool(quality.ApiName,valid);
            if(instance.ReadBool(quality.ApiName)!=valid)throw new InvalidOperationException("PID_PLANT_READBACK: quality differs");
        }

        private void StopController()
        {
            Guard();instance.WriteBool(stop.ApiName,true);
            var until=Stopwatch.StartNew();
            while(until.Elapsed.TotalSeconds<2)
            {
                Guard();
                if(!instance.ReadBool(diagnostics["Running"].ApiName) && instance.ReadBool(stop.ApiName))return;
                Thread.Sleep(20);
            }
            throw new InvalidOperationException("PID_PLANT_STOP_UNVERIFIED: controller did not stop");
        }

        private Dictionary<string,object> Open()
        {
            if(!SimulationRuntimeManager.IsRuntimeManagerAvailable)throw new InvalidOperationException("PID_PLANT_TARGET: Runtime unavailable");
            var infos=SimulationRuntimeManager.RegisteredInstanceInfo??new SInstanceInfo[0];
            var selected=Program.SelectInstanceIdentity(infos.Select(i=>i.Name).ToList(),infos.Select(i=>(int)i.ID).ToList(),instanceName,instanceId);
            if(selected.Count!=1)throw new InvalidOperationException("PID_PLANT_TARGET: instance absent or ambiguous");
            instanceId=(int)infos[selected[0]].ID;
            instance=SimulationRuntimeManager.CreateInterface(instanceId.Value);
            instance.UpdateTagList(ETagListDetails.IODB,false);
            foreach(var tag in instance.TagInfos??new STagInfo[0])
                tags[tag.Name]=new Program.TagMeta{Name=tag.Name,Area=tag.Area.ToString(),Offset=tag.Offset,Bit=tag.Bit,Primitive=tag.PrimitiveDataType.ToString()};
            var declared=(Dictionary<string,object>)bindings["bindings"];
            foreach(var item in declared)
            {
                var descriptor=(Dictionary<string,object>)item.Value;
                if(Convert.ToString(descriptor["db"])!=db || Convert.ToString(descriptor["member"])!=item.Key ||
                    Convert.ToString(descriptor["name"])!=db+"."+item.Key)
                    throw new InvalidOperationException("PID_PLANT_BINDING: diagnostic DB/member mismatch");
                diagnostics[item.Key]=ResolveDb(db,item.Key,Convert.ToString(descriptor["data_type"]));
            }
            for(int i=0;i<16;i++)if(!diagnostics.ContainsKey("Build"+i.ToString("00")))throw new InvalidOperationException("PID_PLANT_PACKAGE: missing Build word");
            stop=diagnostics["CmdStop"];
            if(stop.DataType!="BOOL")throw new InvalidOperationException("PID_PLANT_PACKAGE: CmdStop must be BOOL");
            Guard();measurement=ResolveConnection(input);command=ResolveConnection(output);
            if(Convert.ToString(input["representation"])=="DB_ENGINEERING")
            {
                var storage=(Dictionary<string,object>)input["storage"];
                quality=ResolveDb(Convert.ToString(storage["db"]),Convert.ToString(input["validity_member"]),"BOOL");
                original=Read(measurement);originalQuality=(bool)Read(quality);
            }
            else {originalBytes=ReadWordBytes(measurement);original=(int)Read(measurement);}
            snapshotTaken=true;StopController();
            return new Dictionary<string,object>{{"id",0},{"status","PID_PLANT_READY"},{"instance_name",instanceName},
                {"native_execution_verified",true},{"snapshot",new Dictionary<string,object>{{"measurement",original},{"valid",originalQuality}}}};
        }

        private Dictionary<string,object> Probe()
        {
            if(quality!=null){probePassed=true;return new Dictionary<string,object>{{"status","PID_WORD_PROBE_NOT_REQUIRED"}};}
            var samples=new List<object>();bool restored=false;
            StopController();
            try
            {
                // Try both encodings empirically. Never infer byte order from the machine's endianness.
                WriteRaw(13824);Thread.Sleep(10);int observed=(int)Read(measurement);
                if(observed!=13824){bigEndian=false;WriteRaw(13824);Thread.Sleep(10);}
                if((int)Read(measurement)!=13824)throw new InvalidOperationException("PID_WORD_PROBE_FAILED: cannot determine byte order");
                foreach(int value in new[]{0,13824,27648})
                {
                    WriteRaw(value);Thread.Sleep(10);
                    int byAddress=Decode(ReadWordBytes(measurement),bigEndian),bySymbol=(int)Read(measurement);
                    if(byAddress!=value || bySymbol!=value)throw new InvalidOperationException("PID_WORD_PROBE_FAILED: address/symbol mismatch");
                    samples.Add(new Dictionary<string,object>{{"requested",value},{"address",byAddress},{"symbol",bySymbol}});
                }
            }
            finally
            {
                Guard();instance.InputArea.WriteBytes(measurement.Offset,originalBytes);
                restored=ReadWordBytes(measurement).SequenceEqual(originalBytes) && (int)Read(measurement)==Convert.ToInt32(original);
            }
            if(!restored)throw new InvalidOperationException("PID_WORD_PROBE_FAILED: original input not restored");
            probePassed=true;
            return new Dictionary<string,object>{{"status","PID_WORD_PROBE_PASSED"},{"samples",samples},{"restored",true},{"byte_order",bigEndian?"big":"little"}};
        }

        private Dictionary<string,object> Exchange(Dictionary<string,object> data)
        {
            if(!probePassed)throw new InvalidOperationException("PID_WORD_PROBE_REQUIRED: input transport unverified");
            Guard();double value=Convert.ToDouble(data["measurement"]);
            if(Double.IsNaN(value)||Double.IsInfinity(value)||Single.IsInfinity((float)value)||!(data["valid"] is bool))throw new InvalidOperationException("PID_PLANT_VALUE: finite REAL measurement and BOOL quality required");
            object raw=null;
            if(quality==null)
            {
                if(!(data["measurement_raw"] is int))throw new InvalidOperationException("PID_PLANT_VALUE: INT16 raw required");
                int requested=(int)data["measurement_raw"];WriteRaw(requested);raw=ReadWord(measurement);
                if(Convert.ToInt32(raw)!=requested)throw new InvalidOperationException("PID_PLANT_READBACK: input differs");
            }
            else WriteMeasurement((float)value,(bool)data["valid"]);
            object commandRaw=null;double percent;
            if(Convert.ToString(output["representation"])=="HARDWARE_RAW")
            {
                int n=ReadWord(command);commandRaw=n;var config=(Dictionary<string,object>)output["analog_config"];
                double lo=Convert.ToDouble(config["raw_min"]),hi=Convert.ToDouble(config["raw_max"]);
                percent=(n-lo)/(hi-lo)*100.0;
            }
            else percent=Convert.ToDouble(Read(command));
            if(Double.IsNaN(percent)||Double.IsInfinity(percent)||percent<0||percent>100)
                throw new InvalidOperationException("PID_PLANT_OUTPUT: actual mapped command outside 0..100 percent");
            var values=new Dictionary<string,object>();
            foreach(var pair in diagnostics.Where(p=>!p.Key.StartsWith("Build") && !p.Key.StartsWith("Cmd")))
            {
                object item=Read(pair.Value);
                if(item is float && (Single.IsNaN((float)item)||Single.IsInfinity((float)item)))item=null;
                values[pair.Key]=item;
            }
            return new Dictionary<string,object>{{"status","PID_PLANT_SAMPLE"},{"t_s",clock.Elapsed.TotalSeconds},
                {"measurement",value},{"measurement_raw",raw},{"quality",(bool)data["valid"]},
                {"command_percent",percent},{"command_raw",commandRaw},{"diagnostics",values},{"native_execution_verified",true}};
        }

        private Dictionary<string,object> Close()
        {
            bool stopped=false,restored=false;
            try
            {
                if(instance!=null && snapshotTaken)
                {
                    // Guard precedes Stop AND every restoration write. Changed program => no stale cleanup.
                    StopController();stopped=true;
                    if(quality==null)
                    {
                        Guard();instance.InputArea.WriteBytes(measurement.Offset,originalBytes);
                        restored=ReadWordBytes(measurement).SequenceEqual(originalBytes) && (int)Read(measurement)==Convert.ToInt32(original);
                    }
                    else
                    {
                        WriteMeasurement(Convert.ToSingle(original),originalQuality);
                        restored=Math.Abs(Convert.ToDouble(Read(measurement))-Convert.ToDouble(original))<=.001 && (bool)Read(quality)==originalQuality;
                    }
                    if(!restored)throw new InvalidOperationException("PID_PLANT_CLEANUP_FAILED: input restoration differs");
                }
            }
            catch(Exception error){Program.Log("PID plant cleanup: "+error.ToString());errors.Add(error.Message);}
            var report=new Dictionary<string,object>{{"status","PID_PLANT_CLOSED"},{"cleanup_verified",stopped&&restored},
                {"stop_verified",stopped},{"inputs_restored",restored},{"errors",errors},{"elapsed_s",clock.Elapsed.TotalSeconds}};
            try{if(SimulationRuntimeManager.IsInitialized)SimulationRuntimeManager.Shutdown();}catch(Exception error){errors.Add(error.Message);report["cleanup_verified"]=false;}
            File.WriteAllText(Convert.ToString(request["result_path"]),Program.Json.Serialize(report));
            return report;
        }

        private static void Send(Dictionary<string,object> response){Console.WriteLine(Program.Json.Serialize(response));Console.Out.Flush();}

        [MethodImpl(MethodImplOptions.NoInlining)]
        internal static int Execute(Dictionary<string,object> header)
        {
            PidPlantSession session=null;bool closed=false;object responseId=0;
            try
            {
                session=new PidPlantSession(header);Send(session.Open());
                while(true)
                {
                    var read=Task.Run(()=>Console.ReadLine());
                    double left=session.deadline-session.clock.Elapsed.TotalSeconds;
                    if(left<=0 || !read.Wait((int)Math.Max(1,Math.Min(left*1000,5000))))
                        throw new InvalidOperationException("PID_PLANT_TIMEOUT: deadline or provider inactivity");
                    if(read.Result==null)throw new InvalidOperationException("PID_PLANT_EOF: provider disconnected");
                    var data=Program.Json.Deserialize<Dictionary<string,object>>(read.Result);
                    responseId=data["id"];
                    if(data.ContainsKey("writes") || data.ContainsKey("signals"))throw new InvalidOperationException("PID_PLANT_WRITE: arbitrary writes forbidden");
                    Dictionary<string,object> response;string op=Program.GetString(data,"op","");
                    if(op=="close"){response=session.Close();closed=true;}
                    else if(op=="probe_input_word")response=session.Probe();
                    else if(op=="exchange")response=session.Exchange(data);
                    else throw new InvalidOperationException("PID_PLANT_PROTOCOL: unsupported operation");
                    response["id"]=data["id"];Send(response);
                    if(closed)return session.errors.Count==0?0:1;
                }
            }
            catch(Exception error)
            {
                Program.Log("PID plant request "+Convert.ToString(responseId)+": "+error.ToString());
                if(session!=null)session.errors.Add(error.Message);
                // Protocol errors are visible even when the instance/API cannot be opened.
                Send(new Dictionary<string,object>{{"id",responseId},{"status",error.Message.Split(':')[0]},{"errors",new[]{error.Message}}});
                return 1;
            }
            finally{if(session!=null && !closed)session.Close();}
        }

        internal static void SelfTest(List<object> checks)
        {
            Action<string,Action,bool> check=(name,action,allowed)=>{
                bool passed=true;try{action();passed=allowed;}catch(Exception){passed=!allowed;}
                checks.Add(new Dictionary<string,object>{{"check",name},{"passed",passed}});
                if(!passed)throw new InvalidOperationException("PID plant selftest failed: "+name);
            };
            var binding=new Dictionary<string,object>{{"representation","HARDWARE_RAW"},{"name","AI_Level"},{"data_type","INT"},
                {"address","%IW4"},{"role","MEASUREMENT"},{"permission",true}};
            var manifest=new Dictionary<string,object>{{"loops",new object[]{new Dictionary<string,object>{{"input_binding",binding}}}}};
            check("plant.word_input_allowed",()=>ValidateBinding(binding,"MEASUREMENT",manifest),true);
            binding["address"]="%QW4";check("plant.output_write_denied",()=>ValidateBinding(binding,"MEASUREMENT",manifest),false);
            binding["address"]="%MW4";check("plant.marker_denied",()=>ValidateBinding(binding,"MEASUREMENT",manifest),false);
            var foreign=new Dictionary<string,object>{{"representation","DB_ENGINEERING"},{"name","M_Level"},{"data_type","REAL"},
                {"storage",new Dictionary<string,object>{{"kind","GENERATED_DB"},{"db","DB_Foreign"},{"member","PV"}}},
                {"role","MEASUREMENT"},{"permission",true}};
            ((Dictionary<string,object>)((object[])manifest["loops"])[0])["input_binding"]=foreign;manifest["process_dbs"]=new object[0];
            check("plant.foreign_db_denied",()=>ValidateBinding(foreign,"MEASUREMENT",manifest),false);
            check("plant.changed_identity_denied",()=>CheckIdentity(new int[16],Enumerable.Repeat(1,16).ToArray(),true,true),false);
            check("plant.physical_denied",()=>new PidPlantSession(new Dictionary<string,object>{{"target_type","PHYSICAL_PLC"}}),false);
        }
    }
}
