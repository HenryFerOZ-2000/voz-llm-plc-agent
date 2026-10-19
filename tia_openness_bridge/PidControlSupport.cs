using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.RegularExpressions;
using Siemens.Engineering;
using Siemens.Engineering.SW;
using Siemens.Engineering.SW.Blocks;
using Siemens.Engineering.SW.TechnologicalObjects;
using Siemens.Engineering.Compiler;
using Siemens.Engineering.SW.ExternalSources;
using System.Web.Script.Serialization;
using System.Security.Cryptography;
using System.Xml;
using System.Text;

namespace VozLlmPlcAgent.TiaOpennessBridge
{
    internal static class PidControlSupport
    {
        internal const string Owner = "VozLlmPlcAgent.NativePID.v1";
        internal const string MapOwner = "VozLlmPlcAgent.NativePID.v2";

        // Sources are an import transport, not runtime infrastructure. A unique
        // name and the newly-created handle prove ownership without trusting a
        // filename that the operator may also have used for a manual source.
        internal static void GenerateTemporarySource<T>(Func<string,T> create,Action<T> generate,Action<T> delete)
        {
            T source=create("VozNativePid_"+Guid.NewGuid().ToString("N")+".scl");
            try { generate(source); }
            finally { delete(source); }
        }

        internal static Dictionary<string, object> ValidateManifest(Dictionary<string, object> manifest)
        {
            if (manifest == null || !manifest.ContainsKey("schema_version")
                || !(Object.Equals(manifest["schema_version"],1) || Object.Equals(manifest["schema_version"],2))
                || !manifest.ContainsKey("owner") || Convert.ToString(manifest["owner"]) !=
                    (Object.Equals(manifest["schema_version"],1) ? Owner : MapOwner))
                throw new InvalidOperationException("PID_CONFIG_MISMATCH: malformed manifest");
            object raw;
            if (!manifest.TryGetValue("loops",out raw) || !(raw is IEnumerable) || raw is string)
                throw new InvalidOperationException("PID_CONFIG_MISMATCH: loops missing");
            var loops=((IEnumerable)raw).Cast<object>().Select(x => x as Dictionary<string, object>).ToList();
            if (loops.Count!=1 || loops[0]==null) throw new InvalidOperationException("PID_CONFIG_MISMATCH: one loop required");
            var loop=loops[0];
            if (!loop.ContainsKey("period_ms") || !(loop["period_ms"] is int) || (int)loop["period_ms"]<1 || (int)loop["period_ms"]>60000)
                throw new InvalidOperationException("PID_CYCLIC_OB_UNVERIFIED: invalid period");
            if (!loop.ContainsKey("technology_version") || Convert.ToString(loop["technology_version"])!="2.3")
                throw new InvalidOperationException("PID_UNSUPPORTED_VERSION: requires explicitly verified PID_Compact 2.3");
            var symbols=loop.ContainsKey("symbols") ? loop["symbols"] as Dictionary<string,object> : null;
            var names=new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            foreach (string key in new[]{"fb","db","controller","ob"})
            {
                if (symbols==null || !symbols.ContainsKey(key) || !Regex.IsMatch(Convert.ToString(symbols[key]),@"^[A-Za-z][A-Za-z0-9_]{0,63}$") || !names.Add(Convert.ToString(symbols[key])))
                    throw new InvalidOperationException("PID_BLOCK_CONFLICT: invalid or repeated block name");
            }
            if (!loop.ContainsKey("configuration_hash") || !Regex.IsMatch(Convert.ToString(loop["configuration_hash"]),"^[a-f0-9]{64}$"))
                throw new InvalidOperationException("PID_CONFIG_MISMATCH: configuration fingerprint missing");
            if(Object.Equals(manifest["schema_version"],2))ValidateMapBindings(manifest,loop,names);
            return loop;
        }

        private static List<Dictionary<string,object>> Objects(object raw)
        {
            var list=raw as IEnumerable;
            if(list==null || raw is string)throw new InvalidOperationException("PID_CONFIG_MISMATCH: list required");
            var result=new List<Dictionary<string,object>>();
            foreach(var item in list)
            {
                var value=item as Dictionary<string,object>;
                if(value==null)throw new InvalidOperationException("PID_CONFIG_MISMATCH: object required");
                result.Add(value);
            }
            return result;
        }

        private static void ValidateMapBindings(Dictionary<string,object> manifest,Dictionary<string,object> loop,HashSet<string> blockNames)
        {
            if(loop.ContainsKey("mode") || loop.ContainsKey("simulation") || Convert.ToInt32(loop["period_ms"])!=100)
                throw new InvalidOperationException("PID_CONFIG_MISMATCH: v2 has no environment/model and requires 100ms");
            var expected=new Dictionary<string,string>(StringComparer.OrdinalIgnoreCase);
            foreach(string key in new[]{"input_binding","output_binding"})
            {
                object raw;var binding=loop.TryGetValue(key,out raw)?raw as Dictionary<string,object>:null;
                string role=key=="input_binding"?"MEASUREMENT":"MANIPULATED";
                if(binding==null || !binding.ContainsKey("role") || Convert.ToString(binding["role"])!=role
                    || !binding.ContainsKey("permission") || !Object.Equals(binding["permission"],true))
                    throw new InvalidOperationException("PID_CONFIG_MISMATCH: map binding missing or unauthorized");
                double low=Convert.ToDouble(binding["engineering_min"]),high=Convert.ToDouble(binding["engineering_max"]);
                if(Double.IsNaN(low)||Double.IsInfinity(low)||Double.IsNaN(high)||Double.IsInfinity(high)||low>=high)
                    throw new InvalidOperationException("PID_CONFIG_MISMATCH: finite engineering range required");
                if(Convert.ToString(binding["representation"])=="HARDWARE_RAW")
                {
                    string pattern=role=="MEASUREMENT"?@"^%IW\d+$":@"^%QW\d+$";
                    if(Convert.ToString(binding["data_type"])!="INT" || !Regex.IsMatch(Convert.ToString(binding["address"]),pattern)
                        || !(binding["analog_config"] is Dictionary<string,object>))
                        throw new InvalidOperationException("PID_CONFIG_MISMATCH: hardware binding invalid");
                }
                else if(Convert.ToString(binding["representation"])=="DB_ENGINEERING")
                {
                    var storage=binding["storage"] as Dictionary<string,object>;
                    if(storage==null || Convert.ToString(storage["kind"])!="GENERATED_DB" || Convert.ToString(binding["data_type"])!="REAL")
                        throw new InvalidOperationException("PID_STORAGE_CONFLICT: generated DB required");
                    string db=Convert.ToString(storage["db"]),member=Convert.ToString(storage["member"]);
                    var members=new List<KeyValuePair<string,string>>{new KeyValuePair<string,string>(member,"REAL")};
                    if(role=="MEASUREMENT")members.Add(new KeyValuePair<string,string>(Convert.ToString(binding["validity_member"]),"BOOL"));
                    if(!Regex.IsMatch(db,@"^[A-Za-z][A-Za-z0-9_]{0,63}$") || blockNames.Contains(db))
                        throw new InvalidOperationException("PID_STORAGE_CONFLICT: DB name invalid or occupied");
                    foreach(var item in members)
                    {
                        string path=db+"."+item.Key;
                        if(!Regex.IsMatch(item.Key,@"^[A-Za-z][A-Za-z0-9_]{0,63}$") || expected.ContainsKey(path))
                            throw new InvalidOperationException("PID_STORAGE_CONFLICT: duplicate DB member "+path);
                        expected[path]=item.Value;
                    }
                }
                else throw new InvalidOperationException("PID_CONFIG_MISMATCH: unknown representation");
            }
            if(!manifest.ContainsKey("process_dbs"))throw new InvalidOperationException("PID_STORAGE_CONFLICT: DB descriptors missing");
            var actual=new Dictionary<string,string>(StringComparer.OrdinalIgnoreCase);
            var dbs=new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            foreach(var db in Objects(manifest["process_dbs"]))
            {
                string name=Convert.ToString(db["db"]);
                if(!dbs.Add(name) || Convert.ToString(db["owner"])!=MapOwner)
                    throw new InvalidOperationException("PID_STORAGE_CONFLICT: duplicate/foreign DB descriptor");
                foreach(var member in Objects(db["members"]))
                {
                    string path=name+"."+Convert.ToString(member["name"]);
                    if(actual.ContainsKey(path))throw new InvalidOperationException("PID_STORAGE_CONFLICT: duplicate DB member "+path);
                    actual[path]=Convert.ToString(member["data_type"]);
                }
            }
            if(actual.Count!=expected.Count || expected.Any(e=>!actual.ContainsKey(e.Key) || actual[e.Key]!=e.Value))
                throw new InvalidOperationException("PID_STORAGE_CONFLICT: descriptors differ from bindings");
        }

        internal static void ValidateProcessDbOwnership(Dictionary<string,object> manifest,IEnumerable<PlcBlock> blocks)
        {
            if(!Object.Equals(manifest["schema_version"],2))return;
            var loop=ValidateManifest(manifest);string hash=Convert.ToString(loop["configuration_hash"]);
            foreach(var db in Objects(manifest["process_dbs"]))
            {
                var existing=blocks.SingleOrDefault(b=>String.Equals(b.Name,Convert.ToString(db["db"]),StringComparison.OrdinalIgnoreCase));
                if(existing==null)continue;
                CheckOwner(existing,hash);
                string file=Path.Combine(Path.GetTempPath(),"pid_process_db_"+Guid.NewGuid().ToString("N")+".xml");
                try
                {
                    existing.Export(new FileInfo(file),ExportOptions.WithDefaults);
                    var xml=new XmlDocument();xml.Load(file);
                    var actual=xml.SelectNodes("//*[local-name()='Interface']/*[local-name()='Sections']/*[local-name()='Section']/*[local-name()='Member']")
                        .Cast<XmlNode>().Select(n=>n.Attributes["Name"].Value.ToLowerInvariant()+":"+n.Attributes["Datatype"].Value.ToUpperInvariant()).OrderBy(s=>s).ToArray();
                    var expected=Objects(db["members"]).Select(m=>Convert.ToString(m["name"]).ToLowerInvariant()+":"+Convert.ToString(m["data_type"])).OrderBy(s=>s).ToArray();
                    if(!actual.SequenceEqual(expected))throw new InvalidOperationException("PID_STORAGE_CONFLICT: DB members changed "+existing.Name);
                }
                finally{if(File.Exists(file))File.Delete(file);}
            }
        }

        internal static bool CanUseVerifiedParameters(int version,bool created,bool setByUser,double gain,double ti,double td)
        {
            return version==2 && !created && setByUser && gain>0 && ti>0 && td>=0 &&
                !Double.IsNaN(gain) && !Double.IsInfinity(gain) && !Double.IsNaN(ti) && !Double.IsInfinity(ti) && !Double.IsNaN(td) && !Double.IsInfinity(td);
        }

        internal static void ValidateParameterValues(Dictionary<string,object> values)
        {
            foreach(string key in new[]{"Kp","Ti","Td"})
            {
                if(values==null || !values.ContainsKey(key) || !(values[key] is int || values[key] is long || values[key] is double || values[key] is float || values[key] is decimal))
                    throw new InvalidOperationException("PID_PARAMETER_SAVE: missing numeric "+key);
                double value=Convert.ToDouble(values[key]);float real=(float)value;
                if(Double.IsNaN(value) || Double.IsInfinity(value) || Single.IsNaN(real) || Single.IsInfinity(real)
                    || (key=="Td" ? real<0 : real<=0))
                    throw new InvalidOperationException("PID_PARAMETER_SAVE: invalid "+key);
            }
        }

        internal static void VerifyUploadedParameters(Dictionary<string,object> expected,Dictionary<string,object> actual,bool confirmed)
        {
            ValidateParameterValues(expected);ValidateParameterValues(actual);
            if(!confirmed)throw new InvalidOperationException("PID_PARAMETER_UPLOAD_REQUIRED: confirm the uploaded settings in TIA and save the project.");
            foreach(string key in new[]{"Kp","Ti","Td"})
                if(Math.Abs(Convert.ToDouble(expected[key])-Convert.ToDouble(actual[key]))>0.0001)
                    throw new InvalidOperationException("PID_PARAMETER_UPLOAD_REQUIRED: offline parameters differ from CPU: "+key);
        }

        internal static void ValidateBuildSignatureXml(string text,int[] expected)
        {
            if(expected==null || expected.Length!=16)throw new InvalidOperationException("PID_PARAMETER_SAVE: invalid build identity");
            var xml=new XmlDocument();xml.XmlResolver=null;xml.LoadXml(text);
            for(int i=0;i<16;i++)
            {
                var members=xml.SelectNodes("//*[local-name()='Member' and @Name='Build"+i.ToString("00")+"']");
                if(members.Count!=1)throw new InvalidOperationException("PID_PARAMETER_SAVE: missing build identity member");
                var value=members[0].SelectSingleNode(".//*[local-name()='StartValue']");
                string literal=value==null?"":Regex.Replace(value.InnerText.Trim(),"^Int#","",RegexOptions.IgnoreCase);
                int observed;
                if(!Int32.TryParse(literal,out observed) || observed!=expected[i])
                    throw new InvalidOperationException("PID_PARAMETER_SAVE: offline program differs from runtime package");
            }
        }

        internal static void VerifyExperimentalTarget(string target,string purpose,bool requireSimulation,bool physicalAllowed)
        {
            if(target!="PLCSIM_ADVANCED" || purpose!="experiment" || !requireSimulation || physicalAllowed)
                throw new InvalidOperationException("EXPERIMENT_TARGET_GUARD: native trial requires PLCSIM_ADVANCED");
        }

        internal static void VerifyDownloadTarget(Dictionary<string,object> manifest,string target)
        {
            var loop=ValidateManifest(manifest);
            if(target=="PLCSIM_ADVANCED")return;
            if(Object.Equals(manifest["schema_version"],1))
            {
                if(Convert.ToString(loop["mode"])=="SIMULATION")throw new InvalidOperationException("PID_SIMULATION_TARGET: historical simulated package");
                return;
            }
            foreach(string key in new[]{"input_binding","output_binding"})
            {
                var binding=(Dictionary<string,object>)loop[key];
                if(Convert.ToString(binding["representation"])=="HARDWARE_RAW")
                {
                    var config=(Dictionary<string,object>)binding["analog_config"];
                    if(!config.ContainsKey("confirmed") || !Object.Equals(config["confirmed"],true))
                        throw new InvalidOperationException("PID_CALIBRATION_REQUIRED: "+Convert.ToString(binding["name"]));
                }
            }
        }

        internal static string ExistingDecision(string owner, string hash, string requestedHash)
        {
            if (owner!=Owner) throw new InvalidOperationException("PID_BLOCK_CONFLICT: unmanaged block");
            if (hash!=requestedHash) throw new InvalidOperationException("PID_CONFIG_MISMATCH: explicit migration required");
            return "PRESERVE_PARAMETERS";
        }

        internal static IEnumerable<PlcBlock> AllBlocks(PlcBlockGroup group)
        {
            foreach(var block in group.Blocks) yield return block;
            foreach(var child in group.Groups) foreach(var block in AllBlocks(child)) yield return block;
        }

        internal static void VerifyFileHash(string path,string expected)
        {
            using(var hash=SHA256.Create())using(var file=File.OpenRead(path))
            {
                string actual=BitConverter.ToString(hash.ComputeHash(file)).Replace("-","").ToLowerInvariant();
                if(actual!=expected)throw new InvalidOperationException("PID_CONFIG_MISMATCH: artifact changed "+Path.GetFileName(path));
            }
        }

        internal static void RejectForeignExecutableObs(PlcSoftware plc,Dictionary<string,object> manifest,string directory)
        {
            var loop=ValidateManifest(manifest);string hash=Convert.ToString(loop["configuration_hash"]);
            foreach(var block in AllBlocks(plc.BlockGroup).Where(b=>b is OB))
            {
                try { CheckOwner(block,hash);continue; }catch(InvalidOperationException){}
                string path=Path.Combine(directory,"check_ob_"+block.Number+".xml");
                block.Export(new FileInfo(path),ExportOptions.WithDefaults);
                var xml=new XmlDocument();xml.Load(path);
                var source=xml.SelectSingleNode("//*[local-name()='StructuredText']");
                // An empty ordinary OB is harmless. Other foreign executable code is never overwritten.
                if(source==null || source.ChildNodes.Cast<XmlNode>().Any(n=>n.LocalName!="Blank" && n.LocalName!="NewLine"))
                    throw new InvalidOperationException("PID_BLOCK_CONFLICT: foreign executable OB "+block.Name+". Use a hardware-only template or an owned PID project.");
            }
        }

        internal static string FunctionalSignature(string path)
        {
            var xml=new XmlDocument();xml.Load(path);
            var result=new StringBuilder();
            foreach(XmlNode node in xml.SelectNodes("//Interface | //NetworkSource"))AppendFunctional(node,result);
            return result.ToString();
        }

        private static void AppendFunctional(XmlNode node,StringBuilder result)
        {
            if(new[]{"Blank","NewLine","Comment","MultiLanguageText","LineComment","BlockComment"}.Contains(node.LocalName))return;
            if(node.NodeType==XmlNodeType.Text){result.Append(node.Value.Trim());return;}
            if(node.NodeType!=XmlNodeType.Element)return;
            result.Append('<').Append(node.LocalName);
            foreach(XmlAttribute a in node.Attributes.Cast<XmlAttribute>().OrderBy(a=>a.Name))
                if(a.LocalName!="UId" && a.LocalName!="ID" && a.Prefix!="xmlns" && a.Name!="xmlns")
                    result.Append('|').Append(a.LocalName).Append('=').Append(a.Value);
            result.Append('>');foreach(XmlNode child in node.ChildNodes)AppendFunctional(child,result);
            result.Append("</").Append(node.LocalName).Append('>');
        }

        // Migration from this application's historic PLC_PRG/Main convention: prove that the stored
        // external source reproduces the application blocks before retiring those three blocks in staging.
        // A manually changed block or any extra generated block aborts the copy; the source project stays intact.
        internal static bool RetireVerifiedLegacyProgram(PlcSoftware plc,string directory,bool compileChecks=true)
        {
            var blocks=AllBlocks(plc.BlockGroup).ToList();
            var inventory=blocks.Select(b=>b.Name+":"+b.Number+":"+b.GetType().FullName).OrderBy(n=>n).ToArray();
            if(!blocks.Any(b=>b.Name=="Main"))return false;
            string[] names={"PLC_PRG","DB_PLC_PRG","Main"};
            if(names.Any(n=>blocks.Count(b=>b.Name==n)!=1) || plc.TagTableGroup.TagTables.Find("PLC_Agent_IO")==null)return false;
            var source=plc.ExternalSourceGroup.ExternalSources.Find("siemens_source.scl");if(source==null)return false;
            if(compileChecks && plc.GetService<ICompilable>().Compile().ErrorCount!=0)
                throw new InvalidOperationException("PID_TEMPLATE_COMPILE_REQUIRED: existing template blocks cannot be verified while inconsistent.");
            var before=new Dictionary<string,string>();
            foreach(var b in blocks.Where(b=>names.Contains(b.Name)))
            {
                string path=Path.Combine(directory,"legacy_before_"+before.Count+".xml");b.Export(new FileInfo(path),ExportOptions.WithDefaults);
                before[b.Name]=OwnedBlockFingerprint(b,path);
            }
            var generated=source.GenerateBlocksFromSource(GenerateBlockOption.None);
            var produced=generated.OfType<PlcBlock>().Select(b=>b.Name).OrderBy(n=>n).ToArray();
            if(!produced.SequenceEqual(names.OrderBy(n=>n)))throw new InvalidOperationException("PID_BLOCK_CONFLICT: legacy source is not the application three-block program");
            if(compileChecks && plc.GetService<ICompilable>().Compile().ErrorCount!=0)
                throw new InvalidOperationException("PID_BLOCK_CONFLICT: stored application source does not reproduce a compilable program");
            var after=AllBlocks(plc.BlockGroup).ToList();
            if(!after.Select(b=>b.Name+":"+b.Number+":"+b.GetType().FullName).OrderBy(n=>n).SequenceEqual(inventory))
                throw new InvalidOperationException("PID_BLOCK_CONFLICT: legacy regeneration changes unrelated blocks");
            foreach(var b in after.Where(b=>names.Contains(b.Name)))
            {
                string path=Path.Combine(directory,"legacy_after_"+b.Name+".xml");b.Export(new FileInfo(path),ExportOptions.WithDefaults);
                if(!before.ContainsKey(b.Name) || before[b.Name]!=OwnedBlockFingerprint(b,path))
                    throw new InvalidOperationException("PID_BLOCK_CONFLICT: legacy block differs from its stored generated source: "+b.Name);
            }
            foreach(string name in new[]{"Main","DB_PLC_PRG","PLC_PRG"})AllBlocks(plc.BlockGroup).Single(b=>b.Name==name).Delete();
            return true;
        }

        private static object Canonical(object value)
        {
            var dict=value as Dictionary<string,object>;
            if(dict!=null)return new SortedDictionary<string,object>(dict.ToDictionary(p=>p.Key,p=>Canonical(p.Value)),StringComparer.Ordinal);
            var list=value as IEnumerable;
            if(list!=null && !(value is string))return list.Cast<object>().Select(Canonical).ToArray();
            return value;
        }

        private static string Digest(object value)
        {
            using(var sha=SHA256.Create())return BitConverter.ToString(sha.ComputeHash(
                Encoding.UTF8.GetBytes(new JavaScriptSerializer().Serialize(Canonical(value))))).Replace("-","").ToLowerInvariant();
        }

        internal static string OwnedBlockDigest(int number,string type,string functional,Dictionary<string,object> attributes)
        {
            var stable=new Dictionary<string,object>();
            foreach(string name in new[]{"ProgrammingLanguage","MemoryLayout","AutoNumber","SecondaryType","CyclicTime",
                "PriorityNumber","PhaseOffset","ProcessImagePartNumber","EventsToBeQueued","EventThresholdForTimeError",
                "EnableTimeError","SetENOAutomatically","IsIECCheckEnabled","HeaderAuthor","HeaderFamily","HeaderName",
                "HeaderVersion","ConstantName"})
                if(attributes.ContainsKey(name))stable[name]=Convert.ToString(attributes[name]);
            return Digest(new object[]{number,type,functional,stable});
        }

        private static string OwnedBlockFingerprint(PlcBlock block,string exportedXml)
        {
            var attributes=new Dictionary<string,object>();
            foreach(var info in block.GetAttributeInfos())
                try{attributes[info.Name]=block.GetAttribute(info.Name);}catch(Exception){}
            return OwnedBlockDigest(block.Number,block.GetType().FullName,FunctionalSignature(exportedXml),attributes);
        }

        internal static Dictionary<string,object> CaptureNormalPidInventory(PlcSoftware plc,Dictionary<string,object> manifest,
            string projectPath,string directory)
        {
            var loop=ValidateManifest(manifest);string hash=Convert.ToString(loop["configuration_hash"]);
            var symbols=(Dictionary<string,object>)loop["symbols"];
            var group=plc.BlockGroup.Groups.Find("VozPID_"+hash);
            if(group==null || !AllBlocks(group).Any())throw new InvalidOperationException("PID_BLOCK_CONFLICT: owned PID group missing.");
            foreach(string key in new[]{"fb","db","ob"})
                if(!AllBlocks(group).Any(b=>b.Name==Convert.ToString(symbols[key])))throw new InvalidOperationException("PID_BLOCK_CONFLICT: owned PID block missing.");
            if(plc.TechnologicalObjectGroup.TechnologicalObjects.Find(Convert.ToString(symbols["controller"]))==null)
                throw new InvalidOperationException("PID_BLOCK_CONFLICT: owned PID controller missing.");
            Ensure(plc,manifest);
            var signatures=new Dictionary<string,object>(StringComparer.OrdinalIgnoreCase);
            foreach(var block in AllBlocks(group))
            {
                string file=Path.Combine(directory,"owned_"+Guid.NewGuid().ToString("N")+".xml");
                block.Export(new FileInfo(file),ExportOptions.WithDefaults);
                signatures[block.Name]=OwnedBlockFingerprint(block,file);
            }
            var controller=plc.TechnologicalObjectGroup.TechnologicalObjects.Find(Convert.ToString(symbols["controller"]));
            return new Dictionary<string,object>{{"schema_version",1},{"owner","VozLlmPlcAgent.NormalProgram.v1"},
                {"kind","PID"},{"project_path",Path.GetFullPath(projectPath)}, {"manifest",manifest},
                {"manifest_sha256",Digest(manifest)}, {"configuration_hash",hash}, {"block_signatures",signatures},
                {"controller_identity",controller.CreationDate.ToUniversalTime().Ticks.ToString()}};
        }

        internal static void ValidateNormalPidInventory(Dictionary<string,object> expected,Dictionary<string,object> actual)
        {
            if(expected==null || !Object.Equals(expected["schema_version"],1)
                || Convert.ToString(expected["owner"])!="VozLlmPlcAgent.NormalProgram.v1" || Convert.ToString(expected["kind"])!="PID"
                || !String.Equals(Path.GetFullPath(Convert.ToString(expected["project_path"])),Path.GetFullPath(Convert.ToString(actual["project_path"])),StringComparison.OrdinalIgnoreCase)
                || Convert.ToString(expected["manifest_sha256"])!=Digest(expected["manifest"])
                || Convert.ToString(expected["manifest_sha256"])!=Convert.ToString(actual["manifest_sha256"])
                || Convert.ToString(expected["configuration_hash"])!=Convert.ToString(actual["configuration_hash"])
                || Convert.ToString(expected["controller_identity"])!=Convert.ToString(actual["controller_identity"])
                || Digest(expected["block_signatures"])!=Digest(actual["block_signatures"]))
                throw new InvalidOperationException("PID_BLOCK_CONFLICT: el programa PID fue modificado o no pertenece al proyecto Normal.");
        }

        internal static Dictionary<string,object> ResolveNormalPidState(IEnumerable<Dictionary<string,object>> candidates,
            Func<Dictionary<string,object>,Dictionary<string,object>> capture)
        {
            foreach(var state in candidates)
            {
                if(state==null || !state.ContainsKey("manifest") || Convert.ToString(state["kind"])!="PID")continue;
                try{ValidateNormalPidInventory(state,capture(state));return state;}
                catch(InvalidOperationException){}
            }
            throw new InvalidOperationException("PID_BLOCK_CONFLICT: no hay un registro verificado del programa PID actual.");
        }

        internal static List<string> NormalSourceCollisions(IEnumerable<string> existing,string source)
        {
            var names=new HashSet<string>(existing,StringComparer.OrdinalIgnoreCase);
            return Regex.Matches(source,@"(?im)^\s*(?:FUNCTION_BLOCK|FUNCTION|DATA_BLOCK|ORGANIZATION_BLOCK)\s+""?([A-Za-z][A-Za-z0-9_]*)")
                .Cast<Match>().Select(m=>m.Groups[1].Value).Where(names.Contains).Distinct(StringComparer.OrdinalIgnoreCase).ToList();
        }

        internal static bool RetireNormalPidProgram(PlcSoftware plc,Dictionary<string,object> state,
            Dictionary<string,object> replacement,string projectPath,string directory)
        {
            var groups=plc.BlockGroup.Groups.Where(g=>Regex.IsMatch(g.Name,"^VozPID_[a-f0-9]{64}$")).ToList();
            if(groups.Count==0)return false;
            if(state==null || !state.ContainsKey("manifest"))throw new InvalidOperationException("PID_BLOCK_CONFLICT: falta el registro de propiedad del PID existente.");
            var previous=state["manifest"] as Dictionary<string,object>;
            var loop=ValidateManifest(previous);string hash=Convert.ToString(loop["configuration_hash"]);
            if(groups.Count!=1 || groups[0].Name!="VozPID_"+hash)throw new InvalidOperationException("PID_BLOCK_CONFLICT: grupos PID ajenos o no registrados.");
            ValidateNormalPidInventory(state,CaptureNormalPidInventory(plc,previous,projectPath,directory));
            if(replacement!=null && Convert.ToString(ValidateManifest(replacement)["configuration_hash"])==hash)return false;
            var symbols=(Dictionary<string,object>)loop["symbols"];
            foreach(var block in AllBlocks(groups[0]).OrderBy(b=>b is OB?0:1).ToList())block.Delete();
            plc.TechnologicalObjectGroup.TechnologicalObjects.Find(Convert.ToString(symbols["controller"])).Delete();
            groups[0].Delete();
            return true;
        }

        internal static void NormalProgramSelfTest(List<object> checks)
        {
            foreach(string name in new[]{"owned_program","modified_block","extra_block","changed_controller","wrong_project","changed_manifest",
                "changed_ob_period","changed_layout","compiler_timestamps","pending_record","stale_pending_record","foreign_discrete_collision"})
            {
                var json=new JavaScriptSerializer();
                var manifest=new Dictionary<string,object>{{"configuration_hash","test"}};
                var good=new Dictionary<string,object>{{"schema_version",1},{"owner","VozLlmPlcAgent.NormalProgram.v1"},{"kind","PID"},
                    {"project_path",Path.Combine(Path.GetTempPath(),"Normal.ap18")},{"manifest",manifest},{"manifest_sha256",Digest(manifest)},
                    {"configuration_hash","test"},{"controller_identity","123"},{"block_signatures",new Dictionary<string,object>{{"OB_PID","verified"}}}};
                var actual=json.Deserialize<Dictionary<string,object>>(json.Serialize(good));
                bool passed;
                if(name=="pending_record" || name=="stale_pending_record")
                {
                    var changed=json.Deserialize<Dictionary<string,object>>(json.Serialize(good));changed["controller_identity"]="456";
                    var selected=ResolveNormalPidState(new[]{good,changed},state=>name=="pending_record"?changed:good);
                    passed=Object.ReferenceEquals(selected,name=="pending_record"?changed:good);
                }
                else if(name=="foreign_discrete_collision")
                    passed=NormalSourceCollisions(new[]{"PLC_PRG","UserFB"},"FUNCTION_BLOCK \"PLC_PRG\"\nEND_FUNCTION_BLOCK\nDATA_BLOCK \"DB_PLC_PRG\"").SequenceEqual(new[]{"PLC_PRG"});
                else
                {
                if(name=="changed_ob_period" || name=="changed_layout" || name=="compiler_timestamps")
                {
                    var before=new Dictionary<string,object>{{"CyclicTime",100000},{"MemoryLayout","Optimized"},{"CompileDate","before"}};
                    var after=new Dictionary<string,object>(before);
                    if(name=="changed_ob_period")after["CyclicTime"]=200000;
                    if(name=="changed_layout")after["MemoryLayout"]="Standard";
                    if(name=="compiler_timestamps")after["CompileDate"]="after";
                    ((Dictionary<string,object>)good["block_signatures"])["OB_PID"]=OwnedBlockDigest(30,"OB","call",before);
                    ((Dictionary<string,object>)actual["block_signatures"])["OB_PID"]=OwnedBlockDigest(30,"OB","call",after);
                }
                if(name=="modified_block")((Dictionary<string,object>)actual["block_signatures"])["OB_PID"]="changed";
                if(name=="extra_block")((Dictionary<string,object>)actual["block_signatures"])["ForeignFB"]="foreign";
                if(name=="changed_controller")actual["controller_identity"]="456";
                if(name=="wrong_project")actual["project_path"]=Path.Combine(Path.GetTempPath(),"Foreign.ap18");
                if(name=="changed_manifest")manifest["configuration_hash"]="changed";
                bool rejected=false;try{ValidateNormalPidInventory(good,actual);}catch(InvalidOperationException){rejected=true;}
                passed=rejected!=(name=="owned_program" || name=="compiler_timestamps");
                }
                checks.Add(new Dictionary<string,object>{{"normal_pid_case",name},{"passed",passed}});
                if(!passed)throw new InvalidOperationException("Normal PID ownership self-test: "+name);
            }
        }

        internal static void CheckOwner(PlcBlock block,string hash)
        {
            IEngineeringObject parent=block.Parent;
            for(int i=0;parent!=null && i<12;i++)
            {
                try { if(Convert.ToString(parent.GetAttribute("Name"))=="VozPID_"+hash)return; }catch(Exception){}
                var property=parent.GetType().GetProperty("Parent");
                parent=property==null?null:property.GetValue(parent,null) as IEngineeringObject;
            }
            throw new InvalidOperationException("PID_BLOCK_CONFLICT: block is outside the owned configuration group: "+block.Name);
        }

        internal static Dictionary<string,object> VerifyForDownload(PlcSoftware plc,Dictionary<string,object> manifest)
        {
            var loop=ValidateManifest(manifest);var symbols=(Dictionary<string,object>)loop["symbols"];
            if(plc.TechnologicalObjectGroup.TechnologicalObjects.Find(Convert.ToString(symbols["controller"]))==null)
                throw new InvalidOperationException("PID_COMPILE_REQUIRED: native controller missing before download");
            var ob=VerifyCyclic(plc,manifest,false);
            string directory=Path.Combine(Path.GetTempPath(),"pid_download_check_"+Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(directory);
            RejectForeignExecutableObs(plc,manifest,directory);
            var infrastructure=Ensure(plc,manifest);
            return new Dictionary<string,object>{{"cyclic_ob",ob},{"infrastructure",infrastructure}};
        }

        internal static void MarkOwner(PlcBlock block,string hash)
        {
            CheckOwner(block,hash);
        }

        internal static Dictionary<string,object> Ensure(PlcSoftware plc,Dictionary<string,object> manifest)
        {
            var loop=ValidateManifest(manifest);
            var symbols=(Dictionary<string,object>)loop["symbols"];
            string hash=Convert.ToString(loop["configuration_hash"]);
            var group=plc.BlockGroup.Groups.Find("VozPID_"+hash);
            var blocks=AllBlocks(plc.BlockGroup).ToList();
            ValidateProcessDbOwnership(manifest,blocks);
            foreach(string key in new[]{"fb","db","ob"})
            {
                var block=blocks.SingleOrDefault(b=>String.Equals(b.Name,Convert.ToString(symbols[key]),StringComparison.OrdinalIgnoreCase));
                if(block!=null) CheckOwner(block,hash);
            }
            int number=Convert.ToInt32(loop["ob_number"]);
            if(blocks.Any(b=>b is OB && b.Number==number && b.Name!=Convert.ToString(symbols["ob"])))
                throw new InvalidOperationException("PID_BLOCK_CONFLICT: cyclic OB number is occupied");
            string name=Convert.ToString(symbols["controller"]);
            var obj=plc.TechnologicalObjectGroup.TechnologicalObjects.Find(name);
            if(obj==null && blocks.Any(b=>String.Equals(b.Name,name,StringComparison.OrdinalIgnoreCase)))
                throw new InvalidOperationException("PID_BLOCK_CONFLICT: controller name occupied by ordinary block");
            bool created=obj==null;
            if(!created)
            {
                if(group==null)throw new InvalidOperationException("PID_BLOCK_CONFLICT: foreign technology object");
                var fb=blocks.SingleOrDefault(b=>b.Name==Convert.ToString(symbols["fb"]));
                if(fb==null)throw new InvalidOperationException("PID_BLOCK_CONFLICT: controller ownership binding missing");
                CheckOwner(fb,hash);
                string file=Path.Combine(Path.GetTempPath(),"pid_owner_"+Guid.NewGuid().ToString("N")+".xml");
                try
                {
                    fb.Export(new FileInfo(file),ExportOptions.WithDefaults);
                    string expected="PID_OWNER_BINDING:"+obj.CreationDate.ToUniversalTime().Ticks;
                    if(!File.ReadAllText(file).Contains(expected))throw new InvalidOperationException("PID_BLOCK_CONFLICT: technology creation identity differs");
                }
                finally { if(File.Exists(file))File.Delete(file); }
                if(obj.OfSystemLibElement!="PID_Compact" || obj.OfSystemLibVersion!=new Version(Convert.ToString(loop["technology_version"])))
                    throw new InvalidOperationException("PID_UNSUPPORTED_VERSION: existing technology differs");
            }
            else obj=plc.TechnologicalObjectGroup.TechnologicalObjects.Create(name,"PID_Compact",new Version(Convert.ToString(loop["technology_version"])));
            bool mapDriven=Object.Equals(manifest["schema_version"],2);
            var input=(Dictionary<string,object>)loop[mapDriven?"input_binding":"input_config"];
            var values=new Dictionary<string,object>{
                {"RunModeByStartup",false},{"Config.InputPerOn",false},{"Config.InputLowerLimit",Convert.ToSingle(input["engineering_min"])},
                {"Config.InputUpperLimit",Convert.ToSingle(input["engineering_max"])},{"Config.OutputLowerLimit",0f},{"Config.OutputUpperLimit",100f},
                {"Config.InvertControl",Convert.ToString(loop["direction"])=="DRAIN"},{"_Config.OutputSelect",1},
                {"Config.SetpointLowerLimit",Convert.ToSingle(input["engineering_min"])},{"Config.SetpointUpperLimit",Convert.ToSingle(input["engineering_max"])}};
            bool sim=!mapDriven && Convert.ToString(loop["mode"])=="SIMULATION";
            if(sim || mapDriven)
            {
                values["CycleTime.EnEstimation"]=false;values["CycleTime.EnMonitoring"]=false;
                values["CycleTime.Value"]=Convert.ToSingle(loop["period_ms"])/1000f;
            }
            foreach(var item in values)
            {
                var parameter=obj.Parameters.Find(item.Key);
                if(parameter==null) throw new InvalidOperationException("PID_UNSUPPORTED_VERSION: parameter missing "+item.Key);
                if(created)
                {
                    try { parameter.Value=Convert.ChangeType(item.Value,parameter.Value.GetType()); }
                    catch(Exception e) { throw new InvalidOperationException("PID_PARAMETER_WRITE: "+item.Key+": "+e.Message,e); }
                }
                if(!ParameterEqual(parameter.Value,item.Value)) throw new InvalidOperationException("PID_CONFIG_MISMATCH: "+item.Key);
            }
            if(created && sim)
            {
                var controller=(Dictionary<string,object>)loop["controller"];
                obj.Parameters.Find("_Retain.CtrlParams.SetByUser").Value=true;
                foreach(var item in new Dictionary<string,object>{{"Retain.CtrlParams.Gain",controller["gain"]},{"Retain.CtrlParams.Ti",controller["ti_seconds"]},
                    {"Retain.CtrlParams.Td",controller["td_seconds"]},{"Retain.CtrlParams.Cycle",Convert.ToSingle(loop["period_ms"])/1000f}})
                {
                    var p=obj.Parameters.Find(item.Key);
                    try { p.Value=Convert.ChangeType(item.Value,p.Value.GetType()); }
                    catch(Exception e) { throw new InvalidOperationException("PID_PARAMETER_WRITE: "+item.Key+": "+e.Message,e); }
                }
            }
            if(group==null)plc.BlockGroup.Groups.Create("VozPID_"+hash);
            var learned=new Dictionary<string,object>();
            foreach(string key in new[]{"Retain.CtrlParams.Gain","Retain.CtrlParams.Ti","Retain.CtrlParams.Td"}) learned[key]=obj.Parameters.Find(key).Value;
            bool verified=CanUseVerifiedParameters(mapDriven?2:1,created,Convert.ToBoolean(obj.Parameters.Find("_Retain.CtrlParams.SetByUser").Value),
                Convert.ToDouble(learned["Retain.CtrlParams.Gain"]),Convert.ToDouble(learned["Retain.CtrlParams.Ti"]),Convert.ToDouble(learned["Retain.CtrlParams.Td"]));
            return new Dictionary<string,object>{{"technology_created",created},{"technology_version",obj.OfSystemLibVersion.ToString()},
                {"parameters_verified_offline",verified},
                {"configuration_hash",hash},{"parameters_preserved",!created},{"controller_parameters",learned},{"checked_configuration",values}};
        }

        private static bool ParameterEqual(object a,object b)
        {
            if(a is bool || b is bool) return Object.Equals(a,b);
            return Math.Abs(Convert.ToDouble(a)-Convert.ToDouble(b))<=0.000001;
        }

        internal static Dictionary<string,object> VerifyCyclic(PlcSoftware plc,Dictionary<string,object> manifest,bool mark)
        {
            var loop=ValidateManifest(manifest);var symbols=(Dictionary<string,object>)loop["symbols"];
            string hash=Convert.ToString(loop["configuration_hash"]);
            foreach(string key in new[]{"fb","db","ob"})
            {
                var block=AllBlocks(plc.BlockGroup).Single(b=>b.Name==Convert.ToString(symbols[key]));
                if(mark) MarkOwner(block,hash); else CheckOwner(block,hash);
            }
            var ob=AllBlocks(plc.BlockGroup).Single(b=>b.Name==Convert.ToString(symbols["ob"]));
            int micros=checked(Convert.ToInt32(loop["period_ms"])*1000);
            if(!(ob is OB) || Convert.ToString(ob.GetAttribute("SecondaryType"))!="CyclicInterrupt")
                throw new InvalidOperationException("PID_CYCLIC_OB_UNVERIFIED: wrong OB type");
            if(mark) ob.SetAttribute("CyclicTime",micros);
            ValidateActualCyclic(Convert.ToString(ob.GetAttribute("SecondaryType")),Convert.ToInt32(ob.GetAttribute("CyclicTime")),micros);
            return BlockInfo(ob);
        }

        internal static void ValidateActualCyclic(string type,int actualMicros,int expectedMicros)
        {
            if(type!="CyclicInterrupt" || actualMicros!=expectedMicros)
                throw new InvalidOperationException("PID_CYCLIC_OB_UNVERIFIED: actual type/period differs");
        }

        internal static Dictionary<string,object> Inspect(PlcSoftware plc)
        {
            var objects=new List<object>();
            foreach (var obj in plc.TechnologicalObjectGroup.TechnologicalObjects)
                objects.Add(new Dictionary<string,object>{{"name",obj.Name},{"type",obj.OfSystemLibElement},{"version",obj.OfSystemLibVersion.ToString()}});
            var blocks=new List<object>();
            foreach(var block in plc.BlockGroup.Blocks) blocks.Add(BlockInfo(block));
            return new Dictionary<string,object>{{"technology_objects",objects},{"blocks",blocks},{"plc_name",plc.Name}};
        }

        internal static Dictionary<string,object> BlockInfo(PlcBlock block)
        {
            var attrs=new Dictionary<string,object>();
            foreach (var info in block.GetAttributeInfos())
            {
                try { var value=block.GetAttribute(info.Name); attrs[info.Name]=value==null?null:Convert.ToString(value,System.Globalization.CultureInfo.InvariantCulture); }
                catch(Exception e) { attrs[info.Name]="UNREADABLE: "+e.Message; }
            }
            return new Dictionary<string,object>{{"name",block.Name},{"number",block.Number},{"attributes",attrs}};
        }

        // Development copy only. The caller creates it using Archive/Retrieve, never a folder copy.
        internal static Dictionary<string,object> Probe(PlcSoftware plc,string directory)
        {
            var report=Inspect(plc);
            var obj=plc.TechnologicalObjectGroup.TechnologicalObjects.Find("PID_Probe");
            if(obj==null) obj=plc.TechnologicalObjectGroup.TechnologicalObjects.Create("PID_Probe","PID_Compact",new Version("2.3"));
            report["technology_version"]=obj.OfSystemLibVersion.ToString();
            report["technology_type"]=obj.OfSystemLibElement;
            var parameters=new Dictionary<string,object>();
            foreach (var p in obj.Parameters) parameters[p.Name]=p.Value;
            report["parameters"]=parameters;
            File.WriteAllText(Path.Combine(directory,"parameters.json"),new JavaScriptSerializer().Serialize(report));
            string sourcePath=Path.Combine(directory,"cyclic_probe.scl");
            if(plc.BlockGroup.Blocks.Find("OB30")==null)
            {
                File.WriteAllText(sourcePath,"ORGANIZATION_BLOCK OB30\n{ S7_Optimized_Access := 'TRUE' }\nVERSION : 0.1\nBEGIN\nEND_ORGANIZATION_BLOCK\n");
                var source=plc.ExternalSourceGroup.ExternalSources.CreateFromFile("cyclic_probe.scl",sourcePath);
                source.GenerateBlocksFromSource(GenerateBlockOption.None);
            }
            var ob=plc.BlockGroup.Blocks.Find("OB30");
            report["cyclic_attribute_access"]=ob.GetAttributeInfos().Where(a=>a.Name=="CyclicTime").Select(a=>a.AccessMode.ToString()).ToList();
            try { ob.SetAttribute("CyclicTime",100000); report["cyclic_time_settable"]=true; }
            catch(Exception e) { report["cyclic_time_settable"]=false; report["cyclic_time_set_error"]=e.Message; }
            var compiled=plc.GetService<ICompilable>().Compile();
            report["compile_errors"]=compiled.ErrorCount;
            report["compile_state"]=compiled.State.ToString();
            File.WriteAllText(Path.Combine(directory,"parameters.json"),new JavaScriptSerializer().Serialize(report));
            if(obj.IsConsistent) obj.Export(new FileInfo(Path.Combine(directory,"pid_probe_readonly.xml")),ExportOptions.WithDefaults|ExportOptions.WithReadOnly);
            report["after"]=Inspect(plc);
            foreach (var block in plc.BlockGroup.Blocks)
                if(block is OB) block.Export(new FileInfo(Path.Combine(directory,"ob_readonly_"+block.Number+".xml")),ExportOptions.WithDefaults|ExportOptions.WithReadOnly);
            return report;
        }

        internal static void SelfTest(List<object> checks)
        {
            Func<Dictionary<string,object>> good=()=> {
                var symbols=new Dictionary<string,object>{{"fb","FB_PID_Probe"},{"db","DB_PID_Probe"},{"controller","PID_Probe"},{"ob","OB_PID_Probe"}};
                var loop=new Dictionary<string,object>{{"period_ms",100},{"technology_version","2.3"},{"configuration_hash",new string('a',64)},{"symbols",symbols}};
                return new Dictionary<string,object>{{"schema_version",1},{"owner",Owner},{"loops",new object[]{loop}}};
            };
            Action<string,Action,string> check=(name,action,expected)=>{
                string actual="OK";try{action();}catch(Exception e){actual=e.Message.Split(':')[0];}
                checks.Add(new Dictionary<string,object>{{"pid_case",name},{"passed",actual==expected},{"actual",actual},{"expected",expected}});
                if(actual!=expected) throw new InvalidOperationException("PID self test failed: "+name);
            };
            check("malformed",()=>ValidateManifest(new Dictionary<string,object>()),"PID_CONFIG_MISMATCH");
            Action<string,string,string,bool,bool,bool> experimental=(name,target,purpose,simulation,physical,expected)=>{
                bool accepted=true;try{VerifyExperimentalTarget(target,purpose,simulation,physical);}catch(InvalidOperationException){accepted=false;}
                checks.Add(new Dictionary<string,object>{{"native_experimental_case",name},{"passed",accepted==expected}});
                if(accepted!=expected)throw new InvalidOperationException("Experimental native target check failed: "+name);
            };
            experimental("virtual_allowed","PLCSIM_ADVANCED","experiment",true,false,true);
            experimental("physical_rejected","PHYSICAL_PLC","experiment",true,false,false);
            experimental("wrong_purpose_rejected","PLCSIM_ADVANCED","normal",true,false,false);
            experimental("physical_flag_rejected","PLCSIM_ADVANCED","experiment",true,true,false);
            Action<string,Action,bool> parameters=(name,action,expected)=>{
                bool accepted=true;try{action();}catch(InvalidOperationException){accepted=false;}
                checks.Add(new Dictionary<string,object>{{"pid_parameter_case",name},{"passed",accepted==expected}});
                if(accepted!=expected)throw new InvalidOperationException("PID parameter check failed: "+name);
            };
            Func<double,double,double,Dictionary<string,object>> gains=(kp,ti,td)=>new Dictionary<string,object>{{"Kp",kp},{"Ti",ti},{"Td",td}};
            parameters("valid",()=>ValidateParameterValues(gains(2,10,0)),true);
            parameters("saved_status",()=>{if(!Program.IsSuccessfulStatus("PID_PARAMETERS_SAVED") || Program.IsSuccessfulStatus("PID_PARAMETER_SAVE_FAILED"))throw new InvalidOperationException();},true);
            parameters("serialized_real",()=>ValidateParameterValues(new System.Web.Script.Serialization.JavaScriptSerializer().Deserialize<Dictionary<string,object>>(
                "{\"Kp\":93.21863555908203,\"Ti\":1.12000572681427,\"Td\":0.19600099325180054}")),true);
            parameters("nan",()=>ValidateParameterValues(gains(Double.NaN,10,0)),false);
            parameters("zero_gain",()=>ValidateParameterValues(gains(0,10,0)),false);
            parameters("zero_ti",()=>ValidateParameterValues(gains(2,0,0)),false);
            parameters("negative_td",()=>ValidateParameterValues(gains(2,10,-1)),false);
            parameters("overflow",()=>ValidateParameterValues(gains(1e100,10,0)),false);
            parameters("uploaded_match",()=>VerifyUploadedParameters(gains(2,10,0),gains(2.000001,10,0),true),true);
            parameters("uploaded_mismatch",()=>VerifyUploadedParameters(gains(2,10,0),gains(1,20,0),true),false);
            parameters("uploaded_unconfirmed",()=>VerifyUploadedParameters(gains(2,10,0),gains(2,10,0),false),false);
            parameters("uploaded_invalid",()=>VerifyUploadedParameters(gains(2,10,0),gains(Double.NaN,10,0),true),false);
            string buildXml="<Document>"+String.Join("",Enumerable.Range(0,16).Select(i=>"<Member Name='Build"+i.ToString("00")+"'><StartValue>"+i+"</StartValue></Member>"))+"</Document>";
            parameters("signature_matches",()=>ValidateBuildSignatureXml(buildXml,Enumerable.Range(0,16).ToArray()),true);
            parameters("signature_mismatch",()=>ValidateBuildSignatureXml(buildXml,new int[16]),false);
            var zero=good(); ((Dictionary<string,object>)((object[])zero["loops"])[0])["period_ms"]=0;
            check("zero_period",()=>ValidateManifest(zero),"PID_CYCLIC_OB_UNVERIFIED");
            var dupe=good(); ((Dictionary<string,object>)((Dictionary<string,object>)((object[])dupe["loops"])[0])["symbols"])["ob"]="PID_Probe";
            check("duplicate_blocks",()=>ValidateManifest(dupe),"PID_BLOCK_CONFLICT");
            check("preserve_parameters",()=>{if(ExistingDecision(Owner,"a","a")!="PRESERVE_PARAMETERS")throw new Exception();},"OK");
            check("foreign_block",()=>ExistingDecision("Other","a","a"),"PID_BLOCK_CONFLICT");
            check("config_migration",()=>ExistingDecision(Owner,"a","b"),"PID_CONFIG_MISMATCH");
            check("download_period",()=>ValidateActualCyclic("CyclicInterrupt",200000,100000),"PID_CYCLIC_OB_UNVERIFIED");
            check("download_ob_type",()=>ValidateActualCyclic("ProgramCycle",100000,100000),"PID_CYCLIC_OB_UNVERIFIED");
            Func<Dictionary<string,object>> goodMap=()=>{
                var m=good();m["schema_version"]=2;m["owner"]=MapOwner;
                var l=(Dictionary<string,object>)((object[])m["loops"])[0];
                Func<string,string,Dictionary<string,object>> binding=(role,member)=>new Dictionary<string,object>{
                    {"role",role},{"permission",true},{"engineering_min",0.0},{"engineering_max",100.0},
                    {"representation","DB_ENGINEERING"},{"data_type","REAL"},{"validity_member","LevelValid"},
                    {"storage",new Dictionary<string,object>{{"kind","GENERATED_DB"},{"db","DB_Process"},{"member",member}}}};
                l["input_binding"]=binding("MEASUREMENT","Level");l["output_binding"]=binding("MANIPULATED","Fill");
                m["process_dbs"]=new object[]{new Dictionary<string,object>{{"db","DB_Process"},{"owner",MapOwner},
                    {"members",new object[]{new Dictionary<string,object>{{"name","Level"},{"data_type","REAL"}},
                        new Dictionary<string,object>{{"name","LevelValid"},{"data_type","BOOL"}},
                        new Dictionary<string,object>{{"name","Fill"},{"data_type","REAL"}}}}}};
                return m;
            };
            var noBinding=goodMap();((Dictionary<string,object>)((object[])noBinding["loops"])[0]).Remove("input_binding");
            check("v2_missing_bindings",()=>ValidateManifest(noBinding),"PID_CONFIG_MISMATCH");
            var hasMode=goodMap();((Dictionary<string,object>)((object[])hasMode["loops"])[0])["mode"]="SIMULATION";
            check("v2_rejects_mode",()=>ValidateManifest(hasMode),"PID_CONFIG_MISMATCH");
            var collision=goodMap();var processDb=(Dictionary<string,object>)((object[])collision["process_dbs"])[0];
            ((Dictionary<string,object>)((object[])processDb["members"])[1])["name"]="level";
            check("v2_db_member_collision",()=>ValidateManifest(collision),"PID_STORAGE_CONFLICT");
            check("v2_untuned_new",()=>{if(CanUseVerifiedParameters(2,true,true,2,20,0))throw new Exception();},"OK");
            check("v2_verified_parameters",()=>{ValidateManifest(goodMap());if(!CanUseVerifiedParameters(2,false,true,1.75,20,0))throw new Exception();},"OK");
            check("v1_demo_not_verified",()=>{if(CanUseVerifiedParameters(1,false,true,2,20,0))throw new Exception();},"OK");
        }
    }
}
