using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Text.RegularExpressions;
using System.Web.Script.Serialization;

using Siemens.Engineering;
using Siemens.Engineering.Compiler;
using Siemens.Engineering.Connection;
using Siemens.Engineering.Download;
using Siemens.Engineering.Download.Configurations;
using Siemens.Engineering.HW;
using Siemens.Engineering.HW.Features;
using Siemens.Engineering.SW;
using Siemens.Engineering.SW.Blocks;
using Siemens.Engineering.SW.ExternalSources;
using Siemens.Engineering.SW.Tags;

namespace VozLlmPlcAgent.TiaOpennessBridge
{
    internal static class Program
    {
        private static readonly JavaScriptSerializer Json = new JavaScriptSerializer();
        private static readonly string PortalRoot = @"C:\Program Files\Siemens\Automation\Portal V18";

        private static int Main(string[] args)
        {
            AppDomain.CurrentDomain.AssemblyResolve += ResolveSiemensAssembly;
            if (args.Length != 1 || !File.Exists(args[0]))
            {
                Console.Error.WriteLine("Usage: TiaOpennessBridge.exe <request.json>");
                return 2;
            }

            Dictionary<string, object> request = ReadJson(args[0]);
            string resultPath = GetString(request, "result_path", Path.Combine(Path.GetDirectoryName(args[0]), "tia_compile_report.json"));
            Dictionary<string, object> report;
            try
            {
                string action = GetString(request, "action", "import_compile");
                if (action == "diagnose")
                {
                    report = Diagnose();
                }
                else if (action == "import_compile")
                {
                    report = ExecuteImportAndCompile(request);
                }
                else if (action == "sync_map")
                {
                    report = ExecuteSyncMap(request);
                }
                else if (action == "read_tags")
                {
                    report = ExecuteReadTags(request);
                }
                else if (action == "download")
                {
                    report = ExecuteDownload(request);
                }
                else if (action == "list_connections")
                {
                    report = ExecuteListConnections(request);
                }
                else if (action == "validate_master")
                {
                    report = ExecuteValidateMaster(request);
                }
                else if (action == "evaluate_trial")
                {
                    report = ExecuteEvaluateTrial(request);
                }
                else if (action == "retrieve_probe")
                {
                    report = ExecuteRetrieveProbe(request);
                }
                else if (action == "pid_probe")
                {
                    report = ExecutePidProbe(request);
                }
                else if (action == "native_pid_import_compile")
                {
                    report = ExecuteNativePidCompile(request);
                }
                else if (action == "native_pid_save_parameters")
                {
                    report = ExecuteSaveNativePidParameters(request);
                }
                else if (action == "self_test")
                {
                    // Seccion 18: no hay framework de pruebas C# en este proyecto (solo csc.exe +
                    // ejecucion directa, sin .csproj/MSBuild) - en vez de introducir uno nuevo
                    // (rediseno fuera de alcance), se reutiliza la MISMA infraestructura de
                    // build/ejecucion del bridge para correr aserciones deterministas que no
                    // requieren TIA Portal abierto (NormalizeAddress es una funcion pura).
                    report = RunSelfTest();
                }
                else
                {
                    report = NewReport("TIA_OPENNESS_ERROR");
                    AddError(report, "Unknown action: " + action);
                }
            }
            catch (TagSynchronizationException exception)
            {
                // Seccion 17: distinguir la etapa de reconciliacion de tags (previa a importar la
                // fuente/generar bloques/compilar) del resto de fallos genericos de Openness, para
                // que el pipeline Python pueda mostrar exactamente donde se detuvo.
                report = NewReport("TIA_TAG_SYNC_ERROR");
                AddError(report, exception.Message);
                report["exception"] = exception.ToString();
            }
            catch (Exception exception)
            {
                report = NewReport("TIA_OPENNESS_ERROR");
                AddError(report, exception.GetType().FullName + ": " + exception.Message);
                report["exception"] = exception.ToString();
            }
            if (!report.ContainsKey("success"))
            {
                report["success"] = IsSuccessfulStatus(GetString(report, "status", ""));
            }

            WriteJson(resultPath, report);
            Console.WriteLine(Json.Serialize(report));
            return IsSuccessfulStatus(GetString(report, "status", "")) ? 0 : 1;
        }

        internal static bool IsSuccessfulStatus(string status)
        {
            return status.EndsWith("PASSED",StringComparison.Ordinal) || status=="PID_PARAMETERS_SAVED";
        }

        private sealed class ReconciliationTagInfo
        {
            public string Name;
            public string Address;
        }

        /// <summary>
        /// Pure, TIA-independent classification mirroring the decision rules EnsureTags applies
        /// inline (section 8/9/26): given the tags currently in PLC_Agent_IO and the desired set
        /// for the current program, returns which names to keep unchanged, update (address
        /// differs), create (absent), or delete (orphan - existing name not in desired). No
        /// Siemens API involved, so it can run as a self-test without TIA Portal open.
        /// </summary>
        private static Dictionary<string, List<string>> PlanTagReconciliation(
            List<ReconciliationTagInfo> existingTags, List<ReconciliationTagInfo> desiredTags)
        {
            Dictionary<string, string> existingAddressByName = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
            foreach (ReconciliationTagInfo tag in existingTags)
            {
                existingAddressByName[tag.Name] = tag.Address;
            }

            List<string> keep = new List<string>();
            List<string> update = new List<string>();
            List<string> create = new List<string>();
            List<string> delete = new List<string>();

            HashSet<string> desiredNames = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            foreach (ReconciliationTagInfo tag in desiredTags)
            {
                desiredNames.Add(tag.Name);
                string existingAddress;
                if (!existingAddressByName.TryGetValue(tag.Name, out existingAddress))
                {
                    create.Add(tag.Name);
                    continue;
                }
                bool sameAddress = String.Equals(
                    NormalizeAddress(existingAddress), NormalizeAddress(tag.Address), StringComparison.OrdinalIgnoreCase
                );
                if (sameAddress)
                {
                    keep.Add(tag.Name);
                }
                else
                {
                    update.Add(tag.Name);
                }
            }
            foreach (ReconciliationTagInfo tag in existingTags)
            {
                if (!desiredNames.Contains(tag.Name))
                {
                    delete.Add(tag.Name);
                }
            }

            return new Dictionary<string, List<string>>
            {
                { "keep", keep }, { "update", update }, { "create", create }, { "delete", delete }
            };
        }

        /// <summary>
        /// Deterministic assertions for NormalizeAddress (section 18/21.7) and for
        /// PlanTagReconciliation (section 26/27/28) - runs without opening TIA Portal. Invoke
        /// with a request file containing only {"action": "self_test"}.
        /// </summary>
        private static Dictionary<string, object> RunSelfTest()
        {
            Dictionary<string, object> report = NewReport("SELF_TEST_PASSED");
            List<object> checks = new List<object>();
            report["checks"] = checks;

            Action<string, string, bool> assertEqual = (first, second, expectedEqual) =>
            {
                bool actualEqual = String.Equals(
                    NormalizeAddress(first), NormalizeAddress(second), StringComparison.OrdinalIgnoreCase
                );
                bool passed = actualEqual == expectedEqual;
                checks.Add(new Dictionary<string, object>
                {
                    { "left", first },
                    { "right", second },
                    { "expected_equal", expectedEqual },
                    { "actual_equal", actualEqual },
                    { "passed", passed }
                });
                if (!passed)
                {
                    AddError(
                        report,
                        "NormalizeAddress(" + first + ") vs NormalizeAddress(" + second + "): expected equal="
                        + expectedEqual + " but got " + actualEqual
                    );
                }
            };

            assertEqual("%IX16.0", "%I16.0", true);
            assertEqual("%QX8.0", "%Q8.0", true);
            assertEqual("%MX0.3", "%M0.3", true);
            assertEqual("%I0.0", "%I16.0", false);
            assertEqual("%Q8.0", "%Q8.1", false);
            assertEqual(" %ix16.0 ", "%I16.0", true);

            Action<string, List<string>, string[]> assertPlanBucket = (bucketName, actual, expected) =>
            {
                HashSet<string> actualSet = new HashSet<string>(actual, StringComparer.OrdinalIgnoreCase);
                HashSet<string> expectedSet = new HashSet<string>(expected, StringComparer.OrdinalIgnoreCase);
                bool passed = actualSet.SetEquals(expectedSet);
                checks.Add(new Dictionary<string, object>
                {
                    { "bucket", bucketName },
                    { "expected", expected },
                    { "actual", actual },
                    { "passed", passed }
                });
                if (!passed)
                {
                    AddError(
                        report,
                        "PlanTagReconciliation[" + bucketName + "]: expected [" + String.Join(",", expected)
                        + "] but got [" + String.Join(",", actual) + "]"
                    );
                }
            };

            // Seccion 26: existing A@1,B@2,C@3 - desired A@1,D@2 -> keep A, delete B y C, create D.
            List<ReconciliationTagInfo> existingAbc = new List<ReconciliationTagInfo>
            {
                new ReconciliationTagInfo { Name = "A", Address = "%I0.0" },
                new ReconciliationTagInfo { Name = "B", Address = "%I0.1" },
                new ReconciliationTagInfo { Name = "C", Address = "%I0.2" }
            };
            List<ReconciliationTagInfo> desiredAd = new List<ReconciliationTagInfo>
            {
                new ReconciliationTagInfo { Name = "A", Address = "%I0.0" },
                new ReconciliationTagInfo { Name = "D", Address = "%I0.1" }
            };
            Dictionary<string, List<string>> planAbcToAd = PlanTagReconciliation(existingAbc, desiredAd);
            assertPlanBucket("section26.keep", planAbcToAd["keep"], new[] { "A" });
            assertPlanBucket("section26.update", planAbcToAd["update"], new string[0]);
            assertPlanBucket("section26.create", planAbcToAd["create"], new[] { "D" });
            assertPlanBucket("section26.delete", planAbcToAd["delete"], new[] { "B", "C" });

            // Seccion 16/17/29: programa A (I_Start,I_Stop,Q_Motor,Q_Pilot_Run) -> programa B
            // (I_Start,I_Stop,Q_Valve en la MISMA direccion que Q_Motor) - el resultado final NO
            // debe conservar Q_Motor ni Q_Pilot_Run.
            List<ReconciliationTagInfo> programA = new List<ReconciliationTagInfo>
            {
                new ReconciliationTagInfo { Name = "I_Start", Address = "%I16.0" },
                new ReconciliationTagInfo { Name = "I_Stop", Address = "%I16.1" },
                new ReconciliationTagInfo { Name = "Q_Motor", Address = "%Q8.0" },
                new ReconciliationTagInfo { Name = "Q_Pilot_Run", Address = "%Q8.1" }
            };
            List<ReconciliationTagInfo> programB = new List<ReconciliationTagInfo>
            {
                new ReconciliationTagInfo { Name = "I_Start", Address = "%I16.0" },
                new ReconciliationTagInfo { Name = "I_Stop", Address = "%I16.1" },
                new ReconciliationTagInfo { Name = "Q_Valve", Address = "%Q8.0" }
            };
            Dictionary<string, List<string>> planAtoB = PlanTagReconciliation(programA, programB);
            assertPlanBucket("section16.keep", planAtoB["keep"], new[] { "I_Start", "I_Stop" });
            assertPlanBucket("section16.create", planAtoB["create"], new[] { "Q_Valve" });
            assertPlanBucket("section16.delete", planAtoB["delete"], new[] { "Q_Motor", "Q_Pilot_Run" });

            // Seccion 27: LOCKED persistentes (I_Start/I_Stop) permanecen aunque el programa
            // actual solo necesite Q_Motor - deben llegar en `desired` (Python las agrega, ver
            // tia_openness._build_tag_payload) y quedar en "keep", nunca en "delete".
            List<ReconciliationTagInfo> existingWithLocked = new List<ReconciliationTagInfo>
            {
                new ReconciliationTagInfo { Name = "I_Start", Address = "%I16.0" },
                new ReconciliationTagInfo { Name = "I_Stop", Address = "%I16.1" },
                new ReconciliationTagInfo { Name = "Q_OldMotor", Address = "%Q8.0" }
            };
            List<ReconciliationTagInfo> desiredWithLocked = new List<ReconciliationTagInfo>
            {
                new ReconciliationTagInfo { Name = "I_Start", Address = "%I16.0" },
                new ReconciliationTagInfo { Name = "I_Stop", Address = "%I16.1" },
                new ReconciliationTagInfo { Name = "Q_Motor", Address = "%Q8.0" }
            };
            Dictionary<string, List<string>> planLocked = PlanTagReconciliation(existingWithLocked, desiredWithLocked);
            assertPlanBucket("section27.keep", planLocked["keep"], new[] { "I_Start", "I_Stop" });
            assertPlanBucket("section27.create", planLocked["create"], new[] { "Q_Motor" });
            assertPlanBucket("section27.delete", planLocked["delete"], new[] { "Q_OldMotor" });

            // Fase 1 - politica de DownloadConfiguration (sin TIA).
            Action<string, string, string, bool, bool, string> assertDecision = (checkName, typeName, targetType, startModules, expectedAllowed, expectedSelection) =>
            {
                bool allowed;
                string selection = DecideDownloadConfiguration(typeName, targetType, startModules, out allowed);
                bool passed = allowed == expectedAllowed && String.Equals(selection, expectedSelection, StringComparison.Ordinal);
                checks.Add(new Dictionary<string, object>
                {
                    { "decision", checkName },
                    { "type", typeName },
                    { "target_type", targetType },
                    { "allowed", allowed },
                    { "selection", selection },
                    { "passed", passed }
                });
                if (!passed)
                {
                    AddError(report, "DecideDownloadConfiguration[" + checkName + "]: got allowed=" + allowed + " selection=" + selection);
                }
            };
            assertDecision("plcsim.start", "StartModules", "PLCSIM_ADVANCED", true, true, "StartModule");
            assertDecision("plcsim.start_disabled", "StartModules", "PLCSIM_ADVANCED", false, true, "NoAction");
            assertDecision("plcsim.stop", "StopModules", "PLCSIM_ADVANCED", true, true, "StopAll");
            assertDecision("plcsim.certificate", "DownloadCertificate", "PLCSIM_ADVANCED", true, true, "");
            assertDecision("plcsim.unknown", "ProtectionLevelChanged", "PLCSIM_ADVANCED", true, false, null);
            assertDecision("plcsim.password", "ModuleWriteAccessPassword", "PLCSIM_ADVANCED", true, false, null);
            assertDecision("physical.reinit", "DataBlockReinitialization", "PHYSICAL_PLC", true, false, null);
            assertDecision("physical.certificate", "DownloadCertificate", "PHYSICAL_PLC", true, false, null);
            assertDecision("physical.start", "StartModules", "PHYSICAL_PLC", true, true, "StartModule");

            RunArchiveRetrySelfTest(report, checks);
            RunPidSourceSnapshotSelfTest(report, checks);
            PidControlSupport.SelfTest(checks);
            PidControlSupport.NormalProgramSelfTest(checks);

            if (((List<string>)report["errors"]).Count > 0)
            {
                report["status"] = "SELF_TEST_FAILED";
            }
            return report;
        }

        private static Dictionary<string, object> Diagnose()
        {
            Dictionary<string, object> report = NewReport("DIAGNOSTIC_PASSED");
            report["api_assembly"] = typeof(TiaPortal).Assembly.FullName;
            report["user"] = Environment.UserDomainName + "\\" + Environment.UserName;
            report["portal_root"] = PortalRoot;
            return report;
        }

        private static Dictionary<string, object> ExecutePidProbe(Dictionary<string, object> request)
        {
            string sourcePath=GetRequiredString(request,"project_path");
            string directory=GetRequiredString(request,"development_directory");
            string resumePath=GetString(request,"development_project_path","");
            if(String.IsNullOrEmpty(resumePath))
            {
                if(Directory.Exists(directory)) throw new InvalidOperationException("Development directory must be new.");
                Directory.CreateDirectory(directory);
            }
            else if(!Path.GetFullPath(resumePath).StartsWith(Path.GetFullPath(Path.Combine(directory,"work"))+Path.DirectorySeparatorChar,StringComparison.OrdinalIgnoreCase)
                || !File.Exists(Path.Combine(directory,"NativePID.zap18")))
                throw new InvalidOperationException("Only an Archive/Retrieve development copy can be resumed.");
            var report=NewReport("RUNNING");
            report["physical_download_executed"]=false;
            using(var portal=new TiaPortal(TiaPortalMode.WithoutUserInterface))
            {
                if(String.IsNullOrEmpty(resumePath))
                {
                    Project source=portal.Projects.Open(new FileInfo(sourcePath));
                    try { ArchiveProject(source,directory,"NativePID.zap18",report,"PID",TrialArchiveMaxAttempts); }
                    finally { source.Close(); }
                }
                string archive=Path.Combine(directory,"NativePID.zap18");
                if(!File.Exists(archive)) throw new InvalidOperationException("Development archive was not created.");
                var project=String.IsNullOrEmpty(resumePath)
                    ? portal.Projects.Retrieve(new FileInfo(archive),new DirectoryInfo(Path.Combine(directory,"work")))
                    : portal.Projects.Open(new FileInfo(resumePath));
                try
                {
                    report["development_project_path"]=project.Path.FullName;
                    report["cpu"]=DescribePlcProject(project,GetString(request,"plc_name",""));
                    report["pid_capabilities"]=PidControlSupport.Probe(FindPlcSoftware(project,GetString(request,"plc_name","")),directory);
                    project.Save();
                    report["status"]="PID_PROBE_PASSED";
                }
                finally { project.Close(); }
            }
            return report;
        }

        // An attached project belongs to the operator. Only snapshot saved contents;
        // never save or close it. Import and compile always happen in a separate copy.
        internal static string SnapshotSavedPidSource(bool attached, Func<bool> isModified,
            Func<string> archive, Action close)
        {
            try
            {
                if (isModified()) return "PID_TEMPLATE_UNSAVED_CHANGES";
                return archive();
            }
            finally
            {
                if (!attached) close();
            }
        }

        private static string ArchiveNativePidSource(Dictionary<string, object> request, string directory,
            Dictionary<string, object> report)
        {
            string path = GetRequiredString(request, "project_path");
            TiaPortal sourcePortal = null;
            Project original = null;
            bool attached = false;
            report["failed_stage"] = "open_pid_source";
            try
            {
                if (GetBool(request, "pid_archive_attach_to_running", true))
                {
                    foreach (TiaPortalProcess process in TiaPortal.GetProcesses())
                    {
                        if (process.ProjectPath == null || !PathsEqual(process.ProjectPath.FullName, path)) continue;
                        sourcePortal = process.Attach();
                        original = sourcePortal.Projects.FirstOrDefault(p => PathsEqual(p.Path.FullName, path));
                        if (original == null) throw new InvalidOperationException("PID_SOURCE_CHANGED: el proyecto abierto cambio durante la conexion.");
                        attached = true;
                        report["pid_source_process_id"] = process.Id;
                        break;
                    }
                }
                if (original == null)
                {
                    sourcePortal = new TiaPortal(TiaPortalMode.WithoutUserInterface);
                    original = sourcePortal.Projects.Open(new FileInfo(path));
                }
                report["pid_source_attached"] = attached;
                report["failed_stage"] = "archive_pid_source";
                return SnapshotSavedPidSource(attached,
                    () => { bool modified = original.IsModified; report["pid_source_is_modified"] = modified; return modified; },
                    () => ArchiveProject(original, directory, "NativePID.zap18", report, "PID", TrialArchiveMaxAttempts),
                    () => original.Close());
            }
            finally
            {
                if (sourcePortal != null) sourcePortal.Dispose();
            }
        }

        private static void RunPidSourceSnapshotSelfTest(Dictionary<string, object> report, List<object> checks)
        {
            foreach (string name in new[] { "attached_saved", "attached_unsaved", "owned_saved", "attached_archive_error", "owned_archive_error" })
            {
                bool attached = name.StartsWith("attached", StringComparison.Ordinal);
                bool modified = name == "attached_unsaved";
                bool error = name.EndsWith("archive_error", StringComparison.Ordinal);
                int archives = 0, closes = 0;
                string status = null;
                bool threw = false;
                try
                {
                    status = SnapshotSavedPidSource(attached, () => modified,
                        () => { archives++; if (error) throw new InvalidOperationException("test archive error"); return "CREATED"; },
                        () => { closes++; });
                }
                catch (InvalidOperationException) { threw = true; }
                bool passed = archives == (modified ? 0 : 1) && closes == (attached ? 0 : 1)
                    && threw == error && (error || status == (modified ? "PID_TEMPLATE_UNSAVED_CHANGES" : "CREATED"));
                checks.Add(new Dictionary<string, object> { { "pid_source_case", name }, { "passed", passed },
                    { "archives", archives }, { "closes", closes } });
                if (!passed) AddError(report, "PID source snapshot lifecycle: " + name);
            }
        }

        private static PlcSoftware GenerateNativePidBlocks(Project project,Dictionary<string,object> request,
            Dictionary<string,object> manifest,Dictionary<string,object> loop,Dictionary<string,object> report,
            string directory,bool compileChecks)
        {
            string sourcePath=GetRequiredString(request,"source_path");
            string xmlPath=GetRequiredString(request,"pid_cyclic_ob_path");
            var plc=FindPlcSoftware(project,GetString(request,"plc_name",""));
            if(plc==null) throw new InvalidOperationException("No unique PLC software selected");
            var symbols=(Dictionary<string,object>)loop["symbols"];
            string hash=Convert.ToString(loop["configuration_hash"]);
            // Development verification may explicitly start from a clean hardware-only COPY.
            // This option is never emitted by the normal UI/request builder and never touches the source.
            if(GetBool(request,"pid_development_clean_template",false))
            {
                if(!loop.ContainsKey("mode") || Convert.ToString(loop["mode"])!="SIMULATION") throw new InvalidOperationException("Development cleanup is restricted to historical SIMULATION packages");
                var names=new[]{"Main","PLC_PRG","DB_PLC_PRG","OB30"};
                foreach(var b in PidControlSupport.AllBlocks(plc.BlockGroup).ToList())
                    if(names.Contains(b.Name)) b.Delete();
                report["development_template_cleanup"]=names;
            }
            // Normal mode verifies/regenerates the legacy program before its transaction:
            // newly generated blocks must be compiled before they can be exported.
            else if(compileChecks)report["verified_legacy_program_retired"]=PidControlSupport.RetireVerifiedLegacyProgram(plc,directory,true);
            PidControlSupport.RejectForeignExecutableObs(plc,manifest,directory);
            report["pid_infrastructure"]=PidControlSupport.Ensure(plc,manifest);
            report["tags"]=EnsureTags(plc,request);
            string stagedSource=Path.Combine(directory,"pid.scl");
            var controller=plc.TechnologicalObjectGroup.TechnologicalObjects.Find(Convert.ToString(symbols["controller"]));
            string binding="(* PID_OWNER_BINDING:"+controller.CreationDate.ToUniversalTime().Ticks+" *)";
            string text=File.ReadAllText(sourcePath).Replace("(* PID_OWNER_BINDING *)",binding);
            var info=(Dictionary<string,object>)report["pid_infrastructure"];
            if(Object.Equals(manifest["schema_version"],2) && Convert.ToBoolean(info["parameters_verified_offline"]))
            {
                text=text.Replace("ParametersConfirmed : Bool := FALSE;","ParametersConfirmed : Bool := TRUE;");
                report["offline_parameters_confirmation_restored"]=true;
            }
            File.WriteAllText(stagedSource,text);
            var ownedGroup=plc.BlockGroup.Groups.Find("VozPID_"+hash);
            PidControlSupport.GenerateTemporarySource(
                name=>plc.ExternalSourceGroup.ExternalSources.CreateFromFile(name,stagedSource),
                source=>source.GenerateBlocksFromSource(ownedGroup,GenerateBlockOption.None),
                source=>source.Delete());
            report["pid_external_source_cleanup"]="TEMPORARY_SOURCE_REMOVED";
            string stagedXml=Path.Combine(directory,"ob.xml");File.Copy(xmlPath,stagedXml);
            ownedGroup.Blocks.Import(new FileInfo(stagedXml),ImportOptions.Override);
            report["pid_cyclic_ob"]=PidControlSupport.VerifyCyclic(plc,manifest,true);
            return plc;
        }

        private static void CompileNativePidBlocks(Project project,PlcSoftware plc,Dictionary<string,object> request,
            Dictionary<string,object> manifest,Dictionary<string,object> loop,Dictionary<string,object> report)
        {
            string hash=Convert.ToString(loop["configuration_hash"]);
            var compiled=plc.GetService<ICompilable>().Compile();
            report["error_count"]=compiled.ErrorCount;report["warning_count"]=compiled.WarningCount;
            report["compiler_messages"]=FlattenMessages(compiled.Messages);
            report["cpu"]=DescribePlcProject(project,GetString(request,"plc_name",""));
            report["configuration_hash"]=hash;
            if(compiled.ErrorCount==0)
            {
                report["pid_cyclic_ob"]=PidControlSupport.VerifyCyclic(plc,manifest,false);
                report["pid_infrastructure_after"]=PidControlSupport.Ensure(plc,manifest);
                if(GetString(report,"pid_project_mode","")=="NORMAL_PROJECT")
                    SaveNormalState(project,request,PidControlSupport.CaptureNormalPidInventory(plc,manifest,
                        project.Path.FullName,GetRequiredString(request,"pid_development_directory")),report);
                else { project.Save();report["project_saved"]=true; }
                report["status"]="TIA_COMPILATION_PASSED";
            }
            else { report["project_saved"]=false;report["status"]="TIA_COMPILATION_FAILED"; }
        }

        private static void OpenConfiguredProject(Dictionary<string,object> request,out TiaPortal portal,out Project project,out bool attached)
        {
            string path=GetRequiredString(request,"project_path");
            portal=null;project=null;attached=false;
            Log("[TIA PROJECT] Resolving configured project: "+path);
            if(GetBool(request,"attach_to_running",true))
                foreach(var process in TiaPortal.GetProcesses())
                    if(process.ProjectPath!=null && PathsEqual(process.ProjectPath.FullName,path))
                    {
                        Log("[TIA PROJECT] Attaching to matching TIA session");
                        portal=process.Attach();attached=true;
                        Log("[TIA PROJECT] Attached; locating configured project");
                        project=portal.Projects.FirstOrDefault(p=>PathsEqual(p.Path.FullName,path));
                        if(project==null)throw new InvalidOperationException("TIA_PROJECT_OPEN_FAILED: configured project changed while attaching.");
                        break;
                    }
            if(portal==null){Log("[TIA PROJECT] Starting TIA session");portal=new TiaPortal(GetBool(request,"with_user_interface",true)?TiaPortalMode.WithUserInterface:TiaPortalMode.WithoutUserInterface);}
            if(project==null){Log("[TIA PROJECT] Opening configured project");project=portal.Projects.Open(new FileInfo(path));}
            if(!PathsEqual(project.Path.FullName,path))throw new InvalidOperationException("TIA_PROJECT_OPEN_FAILED: project path mismatch.");
            Log("[TIA PROJECT] Configured project available");
        }

        private static Dictionary<string,object> ReadNormalState(Dictionary<string,object> request,string projectPath,
            PlcSoftware plc=null,string directory=null)
        {
            string path=GetString(request,"normal_program_state_path","");
            if(String.IsNullOrEmpty(path))return null;
            var states=new List<Dictionary<string,object>>();
            foreach(string candidate in new[]{path,path+".pending"})
                if(File.Exists(candidate))
                {
                    var state=ReadJson(candidate);
                    if(!PathsEqual(GetRequiredString(state,"project_path"),projectPath))throw new InvalidOperationException("PID_BLOCK_CONFLICT: Normal ownership record belongs to another project.");
                    states.Add(state);
                }
            if(plc!=null && plc.BlockGroup.Groups.Any(g=>Regex.IsMatch(g.Name,"^VozPID_[a-f0-9]{64}$")))
                return PidControlSupport.ResolveNormalPidState(states,state=>PidControlSupport.CaptureNormalPidInventory(plc,
                    state["manifest"] as Dictionary<string,object>,projectPath,directory));
            return states.FirstOrDefault();
        }

        private static void SaveNormalState(Project project,Dictionary<string,object> request,
            Dictionary<string,object> state,Dictionary<string,object> report)
        {
            string path=GetRequiredString(request,"normal_program_state_path");
            Directory.CreateDirectory(Path.GetDirectoryName(path));
            string pending=path+".pending",temporary=path+"."+Guid.NewGuid().ToString("N")+".tmp";
            WriteJson(temporary,state);
            if(File.Exists(pending))File.Replace(temporary,pending,null);else File.Move(temporary,pending);
            // Persist the complete ownership record before saving the project. If publication
            // fails afterwards, the verified pending record remains recoverable on the next call.
            project.Save();report["project_saved"]=true;
            try{if(File.Exists(path))File.Replace(pending,path,null);else File.Move(pending,path);}
            catch(IOException exception){report["normal_program_state_pending"]=pending;((List<string>)report["warnings"]).Add("Registro recuperable pendiente: "+exception.Message);}
            catch(UnauthorizedAccessException exception){report["normal_program_state_pending"]=pending;((List<string>)report["warnings"]).Add("Registro recuperable pendiente: "+exception.Message);}
        }

        private static void RecoverNormalProject(TiaPortal portal,ref Project project,Dictionary<string,object> report)
        {
            if(!report.ContainsKey("normal_program_backup_path") || GetBool(report,"project_saved",false))return;
            string path=project.Path.FullName;
            try
            {
                // The operator's saved state was checked under exclusive access before backup.
                // These are only our unsaved changes. Reopen the saved project after a failed
                // generation/compile rather than leaving it paired with stale ownership metadata.
                var previous=project;project=null;previous.Close();
                project=portal.Projects.Open(new FileInfo(path));
                report["normal_program_restored"]=true;
            }
            catch(Exception exception)
            {
                report["normal_program_restored"]=false;
                AddError(report,"No se pudo reabrir el proyecto guardado. Respaldo: "+report["normal_program_backup_path"]+". "+exception.Message);
            }
        }

        private static void BackupNormalProject(Project project,Dictionary<string,object> request,Dictionary<string,object> report)
        {
            if(project.IsModified && GetBool(request,"normal_save_before_backup",false))
            {
                Log("[TIA NORMAL] Saving current project before backup");
                project.Save();
                report["normal_input_saved_before_backup"]=true;
                Log("[TIA NORMAL] Current project saved");
            }
            if(project.IsModified)throw new InvalidOperationException("PID_TEMPLATE_UNSAVED_CHANGES: guarde el proyecto TIA antes de generar otro programa.");
            string directory=GetRequiredString(request,"normal_program_backup_directory");
            if(Directory.Exists(directory))throw new InvalidOperationException("Normal backup directory must be new.");
            Directory.CreateDirectory(directory);
            var state=ReadNormalState(request,project.Path.FullName);
            if(state!=null)WriteJson(Path.Combine(directory,"normal_program_state.json"),state);
            string statePath=GetRequiredString(request,"normal_program_state_path")+".pending";
            if(File.Exists(statePath))File.Copy(statePath,Path.Combine(directory,"normal_program_state.pending.json"));
            string status=ArchiveProject(project,directory,"BeforeProgram.zap18",report,"NORMAL",TrialArchiveMaxAttempts);
            report["normal_program_backup_path"]=Path.Combine(directory,"BeforeProgram.zap18");
            if(status!="CREATED")throw new InvalidOperationException(status+": "+GetString(report,"archive_error",""));
        }

        private static Dictionary<string,object> ExecuteSaveNativePidParameters(Dictionary<string,object> request)
        {
            var report=NewReport("PID_PARAMETER_SAVE_FAILED");
            report["project_saved"]=false;report["parameters_verified"]=false;
            report["physical_download_executed"]=false;
            TiaPortal portal=null;Project project=null;bool attached=false;
            bool verificationOnly=GetBool(request,"verification_only",false);
            try
            {
                var parameters=request["parameters"] as Dictionary<string,object>;
                PidControlSupport.ValidateParameterValues(parameters);
                string directory=GetRequiredString(request,"parameter_save_directory");
                PidControlSupport.VerifyFileHash(GetRequiredString(request,"source_path"),GetRequiredString(request,"pid_source_sha256"));
                PidControlSupport.VerifyFileHash(GetRequiredString(request,"pid_manifest_path"),GetRequiredString(request,"pid_manifest_sha256"));
                PidControlSupport.VerifyFileHash(GetRequiredString(request,"pid_bindings_path"),GetRequiredString(request,"pid_bindings_sha256"));
                var manifest=ReadJson(GetRequiredString(request,"pid_manifest_path"));
                var loop=PidControlSupport.ValidateManifest(manifest);
                if(!Object.Equals(manifest["schema_version"],2) || Convert.ToString(loop["configuration_hash"])!=GetRequiredString(request,"configuration_hash"))
                    throw new InvalidOperationException("PID_PARAMETER_SAVE: mismatched controller configuration");
                OpenConfiguredProject(request,out portal,out project,out attached);
                report["project_path"]=project.Path.FullName;report["configuration_hash"]=loop["configuration_hash"];
                using(var access=portal.ExclusiveAccess("Guardar parametros PID verificados"))
                {
                    if(project.IsModified)throw new InvalidOperationException("PID_TEMPLATE_UNSAVED_CHANGES: guarde sus cambios antes de guardar ajustes PID.");
                    var oldState=ReadNormalState(request,project.Path.FullName);
                    if(oldState==null || GetString(oldState,"kind","")!="PID"
                        || GetString(oldState,"configuration_hash","")!=Convert.ToString(loop["configuration_hash"]))
                        throw new InvalidOperationException("PID_PARAMETER_SAVE: missing matching Normal ownership record");
                    BackupNormalProject(project,request,report);
                    report["backup_path"]=report["normal_program_backup_path"];
                    report["backup_sha256"]=Sha256File(Convert.ToString(report["backup_path"]));
                    var plc=FindPlcSoftware(project,GetString(request,"plc_name",""));
                    if(plc==null)throw new InvalidOperationException("PID_PARAMETER_SAVE: PLC software missing");
                    var actual=PidControlSupport.CaptureNormalPidInventory(plc,manifest,project.Path.FullName,directory);
                    PidControlSupport.ValidateNormalPidInventory(oldState,actual);
                    var symbols=(Dictionary<string,object>)loop["symbols"];
                    var fb=FindBlock(plc.BlockGroup,Convert.ToString(symbols["fb"]));
                    string exported=Path.Combine(directory,"BeforePidFB.xml");
                    fb.Export(new FileInfo(exported),ExportOptions.WithDefaults);
                    var signature=((IEnumerable)request["build_signature"]).Cast<object>().Select(v=>Convert.ToInt32(v)).ToArray();
                    PidControlSupport.ValidateBuildSignatureXml(File.ReadAllText(exported),signature);
                    var obj=plc.TechnologicalObjectGroup.TechnologicalObjects.Find(Convert.ToString(symbols["controller"]));
                    var mapping=new Dictionary<string,string>{{"Kp","Retain.CtrlParams.Gain"},{"Ti","Retain.CtrlParams.Ti"},{"Td","Retain.CtrlParams.Td"}};
                    var before=new Dictionary<string,object>();var after=new Dictionary<string,object>();
                    foreach(var item in mapping)before[item.Key]=obj.Parameters.Find(item.Value).Value;
                    report["parameters_before"]=before;
                    if(verificationOnly)
                    {
                        PidControlSupport.VerifyUploadedParameters(parameters,before,
                            Convert.ToBoolean(obj.Parameters.Find("_Retain.CtrlParams.SetByUser").Value));
                        after=before;
                        report["project_saved"]=!project.IsModified;
                        report["save_method"]="TIA_MANUAL_UPLOAD_VERIFIED";
                    }
                    else
                    {
                        foreach(var item in mapping)
                        {
                            var parameter=obj.Parameters.Find(item.Value);
                            parameter.Value=Convert.ChangeType(parameters[item.Key],parameter.Value.GetType());
                            after[item.Key]=Convert.ToDouble(parameter.Value);
                        }
                        PidControlSupport.VerifyUploadedParameters(parameters,after,true);
                        obj.Parameters.Find("_Retain.CtrlParams.SetByUser").Value=true;
                        SaveNormalState(project,request,PidControlSupport.CaptureNormalPidInventory(plc,manifest,project.Path.FullName,directory),report);
                        report["save_method"]="OPENNESS_WRITE_VERIFIED";
                    }
                    PidControlSupport.ValidateParameterValues(after);
                    foreach(var item in mapping)
                        if(Math.Abs(Convert.ToDouble(obj.Parameters.Find(item.Value).Value)-Convert.ToDouble(parameters[item.Key]))>0.0001)
                            throw new InvalidOperationException("PID_PARAMETER_SAVE: saved readback differs");
                    report["parameters_after"]=after;report["parameters_verified"]=true;
                    report["status"]="PID_PARAMETERS_SAVED";
                }
            }
            catch(Exception exception)
            {
                report["status"]="PID_PARAMETER_SAVE_FAILED";
                AddError(report,exception.GetType().FullName+": "+exception.Message);
                if(project!=null && !verificationOnly)RecoverNormalProject(portal,ref project,report);
            }
            finally
            {
                if(project!=null && !attached)try{project.Close();}catch(Exception){}
                if(portal!=null)portal.Dispose();
            }
            return report;
        }

        private static Dictionary<string,object> ExecuteNormalPidCompile(Dictionary<string,object> request)
        {
            var manifest=request["pid_manifest"] as Dictionary<string,object>;
            var loop=PidControlSupport.ValidateManifest(manifest);
            if(!Object.Equals(manifest["schema_version"],2))throw new InvalidOperationException("PID_CONFIG_MISMATCH: Normal in-place requires a map-driven v2 package.");
            string requested=GetRequiredString(request,"project_path");
            if(!PathsEqual(requested,GetRequiredString(request,"template_project_path")))throw new InvalidOperationException("PID_CONFIG_MISMATCH: Normal project differs from configured template.");
            PidControlSupport.VerifyFileHash(GetRequiredString(request,"source_path"),GetRequiredString(request,"pid_source_sha256"));
            PidControlSupport.VerifyFileHash(GetRequiredString(request,"pid_cyclic_ob_path"),GetRequiredString(request,"pid_cyclic_ob_sha256"));
            string directory=GetRequiredString(request,"pid_development_directory");
            if(Directory.Exists(directory))throw new InvalidOperationException("PID_CONFIG_MISMATCH: staging directory must be new.");
            Directory.CreateDirectory(directory);
            var report=NewReport("RUNNING");
            report["pid_project_mode"]="NORMAL_PROJECT";report["project_path"]=requested;
            report["template_project_path"]=requested;report["physical_download_executed"]=false;
            report["original_project_preserved"]=false;report["project_saved"]=false;
            foreach(string key in new[]{"pid_source_sha256","pid_cyclic_ob_sha256","pid_manifest_sha256","pid_bindings_sha256"})
                if(request.ContainsKey(key))report[key]=request[key];
            TiaPortal portal=null;Project project=null;bool attached=false;
            try
            {
                report["failed_stage"]="open_pid_source";
                OpenConfiguredProject(request,out portal,out project,out attached);
                report["attached_to_existing_tia"]=attached;
                Log("[TIA NORMAL] Requesting exclusive access for PID generation");
                using(var access=portal.ExclusiveAccess("Generar PID en proyecto Normal"))
                {
                    Log("[TIA NORMAL] Exclusive access acquired");
                    report["failed_stage"]="backup_normal_project";
                    BackupNormalProject(project,request,report);
                    var plc=FindPlcSoftware(project,GetString(request,"plc_name",""));
                    if(plc==null)throw new InvalidOperationException("No unique PLC software selected.");
                    // Compile is forbidden inside an Openness transaction. Check the old program
                    // first; regeneration/import then forms one undo unit and rolls back on errors.
                    report["failed_stage"]="verify_previous_program";
                    if(plc.GetService<ICompilable>().Compile().ErrorCount!=0)throw new InvalidOperationException("PID_TEMPLATE_COMPILE_REQUIRED: el programa anterior contiene errores.");
                    var state=ReadNormalState(request,project.Path.FullName,plc,directory);
                    report["failed_stage"]="verify_legacy_program";
                    report["verified_legacy_program_retired"]=PidControlSupport.RetireVerifiedLegacyProgram(plc,directory,true);
                    report["failed_stage"]="generate_blocks";
                    using(var transaction=access.Transaction(project,"Programa PID generado"))
                    {
                        report["previous_pid_retired"]=PidControlSupport.RetireNormalPidProgram(plc,state,manifest,project.Path.FullName,directory);
                        plc=GenerateNativePidBlocks(project,request,manifest,loop,report,directory,false);
                        transaction.CommitOnDispose();
                    }
                    report["failed_stage"]="compile";
                    CompileNativePidBlocks(project,plc,request,manifest,loop,report);
                    report.Remove("failed_stage");
                }
                if(GetString(report,"status","")!="TIA_COMPILATION_PASSED")RecoverNormalProject(portal,ref project,report);
            }
            catch(Exception exception)
            {
                report["status"]=exception.Message.StartsWith("PID_TEMPLATE_UNSAVED_CHANGES",StringComparison.Ordinal)
                    ? "PID_TEMPLATE_UNSAVED_CHANGES" : "TIA_OPENNESS_ERROR";
                AddError(report,exception.GetType().FullName+": "+exception.Message);report["exception"]=exception.ToString();
                if(project!=null)RecoverNormalProject(portal,ref project,report);
            }
            finally
            {
                try{if(!attached && project!=null)project.Close();}finally{if(portal!=null)portal.Dispose();}
            }
            return report;
        }

        private static Dictionary<string, object> ExecuteNativePidCompile(Dictionary<string, object> request)
        {
            if(GetString(request,"pid_project_mode","")=="NORMAL_PROJECT")return ExecuteNormalPidCompile(request);
            var manifest=request["pid_manifest"] as Dictionary<string,object>;
            var loop=PidControlSupport.ValidateManifest(manifest);
            string directory=GetRequiredString(request,"pid_development_directory");
            string sourcePath=GetRequiredString(request,"source_path");
            string xmlPath=GetRequiredString(request,"pid_cyclic_ob_path");
            PidControlSupport.VerifyFileHash(sourcePath,GetRequiredString(request,"pid_source_sha256"));
            PidControlSupport.VerifyFileHash(xmlPath,GetRequiredString(request,"pid_cyclic_ob_sha256"));
            if(Directory.Exists(directory)) throw new InvalidOperationException("PID_CONFIG_MISMATCH: staging directory must be new");
            Directory.CreateDirectory(directory);
            var report=NewReport("RUNNING");
            report["physical_download_executed"]=false;
            report["template_project_path"]=GetRequiredString(request,"template_project_path");
            report["original_project_preserved"]=true;
            report["pid_source_sha256"]=GetRequiredString(request,"pid_source_sha256");
            report["pid_cyclic_ob_sha256"]=GetRequiredString(request,"pid_cyclic_ob_sha256");
            foreach(string key in new[]{"pid_manifest_sha256","pid_bindings_sha256"})
                if(request.ContainsKey(key))report[key]=request[key];
            try
            {
                string archiveStatus = ArchiveNativePidSource(request, directory, report);
                if (archiveStatus != "CREATED")
                {
                    report["status"] = archiveStatus;
                    AddError(report, archiveStatus == "PID_TEMPLATE_UNSAVED_CHANGES"
                        ? "La plantilla tiene cambios sin guardar. Guardela en TIA Portal y vuelva a ejecutar; puede dejarla abierta."
                        : archiveStatus + ": " + GetString(report, "archive_error", ""));
                    return report;
                }
            }
            catch (Exception exception)
            {
                report["status"] = GetString(report, "failed_stage", "") == "open_pid_source"
                    ? "TIA_PROJECT_OPEN_FAILED" : "TIA_PID_SNAPSHOT_FAILED";
                AddError(report, exception.GetType().FullName + ": " + exception.Message);
                report["exception"] = exception.ToString();
                return report;
            }
            report.Remove("failed_stage");
            using(var portal=new TiaPortal(TiaPortalMode.WithoutUserInterface))
            {
                if(!File.Exists(Path.Combine(directory,"NativePID.zap18"))) throw new InvalidOperationException("PID_CONFIG_MISMATCH: archive missing");
                var project=portal.Projects.Retrieve(new FileInfo(Path.Combine(directory,"NativePID.zap18")),new DirectoryInfo(Path.Combine(directory,"work")));
                try
                {
                    report["project_path"]=project.Path.FullName;
                    var plc=GenerateNativePidBlocks(project,request,manifest,loop,report,directory,true);
                    CompileNativePidBlocks(project,plc,request,manifest,loop,report);
                }
                finally { project.Close(); }
            }
            return report;
        }

        private static Dictionary<string, object> ExecuteImportAndCompile(Dictionary<string, object> request)
        {
            Dictionary<string, object> report = NewReport("RUNNING");
            string projectPath = GetString(request, "project_path", "");
            string sourcePath = GetRequiredString(request, "source_path");
            string sourceName = GetString(request, "source_name", Path.GetFileName(sourcePath));
            string requestedPlcName = GetString(request, "plc_name", "");
            bool attach = GetBool(request, "attach_to_running", true);
            bool withUi = GetBool(request, "with_user_interface", true);
            bool createTags = GetBool(request, "create_plc_tags", true);
            bool compileAfterImport = GetBool(request, "compile_after_import", true);
            bool saveOnSuccess = GetBool(request, "save_project_on_success", true);

            TiaPortal portal = null;
            Project project = null;
            bool attachedToExisting = false;
            ExclusiveAccess normalAccess=null;
            Transaction normalTransaction=null;
            try
            {
                OpenConfiguredProject(request,out portal,out project,out attachedToExisting);

                PlcSoftware plcSoftware = FindPlcSoftware(project, requestedPlcName);
                if (plcSoftware == null)
                {
                    throw new InvalidOperationException("No PLC software was found in the TIA Portal project.");
                }

                report["attached_to_existing_tia"] = attachedToExisting;
                report["project_path"] = project.Path.FullName;
                report["plc_name"] = plcSoftware.Name;
                report["source_path"] = sourcePath;
                report["physical_download_executed"] = false;

                if(request.ContainsKey("normal_program_state_path"))
                {
                    normalAccess=portal.ExclusiveAccess("Generar programa discreto en proyecto Normal");
                    BackupNormalProject(project,request,report);
                    // Verification regenerates and compiles the old source before export.
                    // Compile is forbidden inside a transaction; backup/reopen recovery
                    // protects this preparation as well as the transactional replacement.
                    report["verified_legacy_program_retired"]=PidControlSupport.RetireVerifiedLegacyProgram(plcSoftware,
                        GetRequiredString(request,"normal_program_backup_directory"),true);
                    normalTransaction=normalAccess.Transaction(project,"Programa discreto generado");
                    report["previous_pid_retired"]=PidControlSupport.RetireNormalPidProgram(plcSoftware,
                        ReadNormalState(request,project.Path.FullName,plcSoftware,GetRequiredString(request,"normal_program_backup_directory")),null,project.Path.FullName,
                        GetRequiredString(request,"normal_program_backup_directory"));
                    var collisions=PidControlSupport.NormalSourceCollisions(PidControlSupport.AllBlocks(plcSoftware.BlockGroup).Select(block=>block.Name),File.ReadAllText(sourcePath));
                    if(collisions.Count>0)throw new InvalidOperationException("PID_BLOCK_CONFLICT: la fuente reemplazaria bloques ajenos: "+String.Join(", ",collisions));
                }

                if (createTags)
                {
                    Dictionary<string, object> tagReconciliation = EnsureTags(plcSoftware, request);
                    report["tags"] = tagReconciliation;
                    // Seccion 22: mismo contenido, nombre explicito para quien lea
                    // tia_compile_report.json buscando especificamente el resumen de
                    // reconciliacion de tags (desired/created/updated/existing/removed).
                    report["tag_reconciliation"] = tagReconciliation;
                }

                PlcExternalSource existing = plcSoftware.ExternalSourceGroup.ExternalSources.Find(sourceName);
                if (existing != null)
                {
                    existing.Delete();
                }
                PlcExternalSource source = plcSoftware.ExternalSourceGroup.ExternalSources.CreateFromFile(sourceName, sourcePath);
                IList<IEngineeringObject> generatedBlocks = source.GenerateBlocksFromSource(GenerateBlockOption.None);
                report["generated_blocks_count"] = generatedBlocks == null ? 0 : generatedBlocks.Count;

                if(normalTransaction!=null)
                {
                    normalTransaction.CommitOnDispose();normalTransaction.Dispose();normalTransaction=null;
                }

                int errorCount = 0;
                int warningCount = 0;
                if (compileAfterImport)
                {
                    ICompilable compilable = plcSoftware.GetService<ICompilable>();
                    if (compilable == null)
                    {
                        throw new InvalidOperationException("The PLC software does not expose the compile service.");
                    }
                    CompilerResult compileResult = compilable.Compile();
                    errorCount = compileResult.ErrorCount;
                    warningCount = compileResult.WarningCount;
                    report["compiler_state"] = compileResult.State.ToString();
                    report["compiler_messages"] = FlattenMessages(compileResult.Messages);
                }

                report["error_count"] = errorCount;
                report["warning_count"] = warningCount;
                bool success = errorCount == 0;
                if (success && saveOnSuccess)
                {
                    if(request.ContainsKey("normal_program_state_path"))
                        SaveNormalState(project,request,new Dictionary<string,object>{{"schema_version",1},
                            {"owner","VozLlmPlcAgent.NormalProgram.v1"},{"kind","DISCRETE"},{"project_path",project.Path.FullName}},report);
                    else {project.Save();report["project_saved"]=true;}
                }
                else
                {
                    report["project_saved"] = false;
                }
                report["status"] = success ? "TIA_COMPILATION_PASSED" : "TIA_COMPILATION_FAILED";
                if(!success && normalAccess!=null)
                {
                    normalAccess.Dispose();normalAccess=null;
                    RecoverNormalProject(portal,ref project,report);
                }
            }
            catch(Exception exception)
            {
                if(!request.ContainsKey("normal_program_state_path"))throw;
                if(normalTransaction!=null){normalTransaction.Dispose();normalTransaction=null;}
                if(normalAccess!=null){normalAccess.Dispose();normalAccess=null;}
                report["status"]=exception.Message.StartsWith("PID_TEMPLATE_UNSAVED_CHANGES",StringComparison.Ordinal)
                    ? "PID_TEMPLATE_UNSAVED_CHANGES" : "TIA_OPENNESS_ERROR";
                report["project_saved"]=GetBool(report,"project_saved",false);
                AddError(report,exception.GetType().FullName+": "+exception.Message);report["exception"]=exception.ToString();
                if(project!=null)RecoverNormalProject(portal,ref project,report);
            }
            finally
            {
                if(normalTransaction!=null)normalTransaction.Dispose();
                if(normalAccess!=null)normalAccess.Dispose();
                if (!attachedToExisting && project != null)
                {
                    project.Close();
                }
                if (portal != null)
                {
                    portal.Dispose();
                }
            }
            return report;
        }

        private static PlcSoftware FindPlcSoftware(Project project, string requestedName)
        {
            List<PlcSoftware> candidates = new List<PlcSoftware>();
            foreach (Device device in project.Devices)
            {
                foreach (DeviceItem item in device.DeviceItems)
                {
                    CollectPlcSoftware(item, candidates);
                }
            }
            if (!String.IsNullOrWhiteSpace(requestedName))
            {
                return candidates.FirstOrDefault(candidate => String.Equals(candidate.Name, requestedName, StringComparison.OrdinalIgnoreCase));
            }
            return candidates.FirstOrDefault();
        }

        private static void CollectPlcSoftware(DeviceItem item, IList<PlcSoftware> result)
        {
            SoftwareContainer container = item.GetService<SoftwareContainer>();
            if (container != null && container.Software is PlcSoftware)
            {
                result.Add((PlcSoftware)container.Software);
            }
            foreach (DeviceItem child in item.DeviceItems)
            {
                CollectPlcSoftware(child, result);
            }
        }

/// <summary>
        /// Full reconciliation (section 8/9) of the PLC_Agent_IO tag table against the request's
        /// `tags` payload - the DESIRED set, already computed by Python as "external tags the
        /// current program actually uses, plus any LOCKED map entry with a functional name"
        /// (tia_openness.py::_build_tag_payload). Treats it as the single source of truth (never
        /// the other way around): after this method returns, set(PLC_Agent_IO) == set(desired)
        /// (section 10). PLC_Agent_IO is a table this application creates and exclusively owns -
        /// every tag inside it is, by construction, "administered" (section 4/15/19); no other
        /// tag table is ever enumerated or touched here.
        ///
        /// Order (section 9, avoids transient address collisions):
        ///   1. validate the desired set itself (no duplicate names, no two names sharing an
        ///      address);
        ///   2. delete every EXISTING tag whose name is not in the desired set (orphans of a
        ///      previous program) - this frees every address a later create/update might need,
        ///      before anything is created or moved;
        ///   3. for each desired tag: same name+type+address -> keep; same name+type, different
        ///      address -> update LogicalAddress in place (PlcTag has no rename, but DOES expose
        ///      a settable LogicalAddress/DataTypeName, confirmed via reflection against
        ///      Siemens.Engineering.dll); same name, incompatible type -> hard error, never a
        ///      silent conversion; name absent -> create.
        ///   4. verify the final table matches the desired set exactly.
        /// A deletion or creation failure never continues silently (section 23) - it raises
        /// TagSynchronizationException with the tag name/address/reason, surfaced by Main() as a
        /// distinct TIA_TAG_SYNC_ERROR status.
        /// </summary>
        private static Dictionary<string, object> EnsureTags(PlcSoftware plcSoftware, Dictionary<string, object> request)
        {
            PlcTagTable table = plcSoftware.TagTableGroup.TagTables.Find("PLC_Agent_IO");
            if (table == null)
            {
                table = plcSoftware.TagTableGroup.TagTables.Create("PLC_Agent_IO");
            }

            object rawTags;
            IEnumerable tagItems = null;
            if (request.TryGetValue("tags", out rawTags))
            {
                tagItems = rawTags as IEnumerable;
            }
            if (tagItems == null)
            {
                throw new InvalidOperationException("The TIA request does not contain a valid tag collection.");
            }

            List<Dictionary<string, object>> tagRequests = new List<Dictionary<string, object>>();
            foreach (object rawTag in tagItems)
            {
                Dictionary<string, object> tag = rawTag as Dictionary<string, object>;
                if (tag == null)
                {
                    throw new InvalidOperationException("The TIA request contains an invalid tag entry.");
                }
                tagRequests.Add(tag);
            }
            if (tagRequests.Count == 0)
            {
                throw new InvalidOperationException("No authorized PLC tags were received; block generation was stopped.");
            }

            // Paso 1: validar el conjunto deseado en si mismo antes de tocar nada en TIA.
            Dictionary<string, string> desiredAddressByName = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
            Dictionary<string, string> desiredTypeByName = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
            Dictionary<string, string> occupantByNormalizedAddress = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
            foreach (Dictionary<string, object> tag in tagRequests)
            {
                string name = GetRequiredString(tag, "name");
                string dataType = GetString(tag, "data_type", "Bool");
                string address = GetRequiredString(tag, "address");
                if (desiredAddressByName.ContainsKey(name))
                {
                    throw new TagSynchronizationException("Duplicate desired tag name: " + name + ".");
                }
                string normalizedAddress = NormalizeAddress(address);
                string otherName;
                if (occupantByNormalizedAddress.TryGetValue(normalizedAddress, out otherName))
                {
                    throw new TagSynchronizationException(
                        "Two desired tags target the same address " + address + ": " + name + " and " + otherName + "."
                    );
                }
                occupantByNormalizedAddress[normalizedAddress] = name;
                desiredAddressByName[name] = address;
                desiredTypeByName[name] = dataType;
            }
            Log("[TIA TAGS] Desired tags: " + desiredAddressByName.Count);

            // Paso 2: eliminar huerfanas - cualquier tag EXISTENTE en PLC_Agent_IO cuyo nombre ya
            // no forme parte del conjunto deseado. Se hace ANTES de crear/actualizar nada, para
            // que ninguna direccion quede reclamada por dos nombres a la vez transitoriamente
            // (seccion 9).
            List<PlcTag> existingSnapshot = new List<PlcTag>();
            foreach (PlcTag tag in table.Tags)
            {
                existingSnapshot.Add(tag);
            }
            Log("[TIA TAGS] Existing managed tags: " + existingSnapshot.Count);

            int removed = 0;
            foreach (PlcTag existingTag in existingSnapshot)
            {
                if (desiredAddressByName.ContainsKey(existingTag.Name))
                {
                    continue;
                }
                string orphanName = existingTag.Name;
                string orphanAddress = existingTag.LogicalAddress;
                try
                {
                    existingTag.Delete();
                }
                catch (Exception exception)
                {
                    throw new TagSynchronizationException(
                        "Could not remove orphan tag " + orphanName + " at " + orphanAddress
                        + " from PLC_Agent_IO: " + exception.Message
                    );
                }
                Log("[TIA TAGS] Removing orphan: " + orphanName + " at " + orphanAddress);
                removed++;
            }

            // Paso 3: crear/actualizar cada tag deseada (huerfanas ya fuera de camino).
            int created = 0;
            int updated = 0;
            int unchanged = 0;
            foreach (Dictionary<string, object> tag in tagRequests)
            {
                string name = GetRequiredString(tag, "name");
                string dataType = desiredTypeByName[name];
                string address = desiredAddressByName[name];
                string normalizedAddress = NormalizeAddress(address);

                PlcTag existingTag = table.Tags.Find(name);
                if (existingTag == null)
                {
                    Log("[TIA TAGS] Creating " + name + " at " + address);
                    table.Tags.Create(name, dataType, address);
                    created++;
                    Log("[TIA TAGS] " + name + " synchronized");
                    continue;
                }

                bool sameType = String.Equals(existingTag.DataTypeName, dataType, StringComparison.OrdinalIgnoreCase);
                if (!sameType)
                {
                    throw new TagSynchronizationException(
                        "Authorized tag type conflict for " + name
                        + ". Existing: " + existingTag.DataTypeName
                        + "; requested: " + dataType
                        + ". Incompatible types are never converted automatically."
                    );
                }

                bool sameAddress = String.Equals(
                    NormalizeAddress(existingTag.LogicalAddress),
                    normalizedAddress,
                    StringComparison.OrdinalIgnoreCase
                );
                if (sameAddress)
                {
                    Log("[TIA TAGS] Keeping: " + name + " at " + address);
                    unchanged++;
                    continue;
                }

                Log("[TIA TAGS] " + name + " existing=" + existingTag.LogicalAddress + " requested=" + address);
                Log("[TIA TAGS] Updating " + name);
                existingTag.LogicalAddress = address;
                updated++;
                Log("[TIA TAGS] " + name + " synchronized");
            }

            // Paso 4: el estado final debe coincidir exactamente con lo deseado (seccion 10/11).
            int finalCount = 0;
            List<string> unexpected = new List<string>();
            foreach (PlcTag tag in table.Tags)
            {
                finalCount++;
                if (!desiredAddressByName.ContainsKey(tag.Name))
                {
                    unexpected.Add(tag.Name);
                }
            }
            if (unexpected.Count > 0 || finalCount != desiredAddressByName.Count)
            {
                throw new TagSynchronizationException(
                    "PLC_Agent_IO does not match the desired tag set after reconciliation. "
                    + "Unexpected: " + String.Join(", ", unexpected)
                    + ". Expected " + desiredAddressByName.Count + " tags, found " + finalCount + "."
                );
            }

            Log("[TIA TAGS] Reconciliation completed");
            Log("[TIA TAGS] Final managed tags: " + finalCount);
            return new Dictionary<string, object>
            {
                { "table", table.Name },
                { "desired", tagRequests.Count },
                { "requested", tagRequests.Count },
                { "created", created },
                { "updated", updated },
                { "existing", unchanged },
                { "kept", unchanged },
                { "removed", removed },
                { "final_count", finalCount }
            };
        }

        private static Dictionary<string, object> ExecuteSyncMap(Dictionary<string, object> request)
        {
            Dictionary<string, object> report = NewReport("RUNNING");
            string projectPath = GetString(request, "project_path", "");
            string requestedPlcName = GetString(request, "plc_name", "");
            bool attach = GetBool(request, "attach_to_running", true);
            bool withUi = GetBool(request, "with_user_interface", true);

            TiaPortal portal = null;
            Project project = null;
            bool attachedToExisting = false;
            try
            {
                if (attach)
                {
                    TiaPortalProcess process = TiaPortal.GetProcesses().FirstOrDefault();
                    if (process != null)
                    {
                        portal = process.Attach();
                        attachedToExisting = true;
                    }
                }
                if (portal == null)
                {
                    portal = new TiaPortal(withUi ? TiaPortalMode.WithUserInterface : TiaPortalMode.WithoutUserInterface);
                }

                project = portal.Projects.FirstOrDefault();
                if (project == null)
                {
                    if (String.IsNullOrWhiteSpace(projectPath) || !File.Exists(projectPath))
                    {
                        throw new FileNotFoundException("No TIA project is open and project_path is invalid.", projectPath);
                    }
                    project = portal.Projects.Open(new FileInfo(projectPath));
                }

                PlcSoftware plcSoftware = FindPlcSoftware(project, requestedPlcName);
                if (plcSoftware == null)
                {
                    throw new InvalidOperationException("No PLC software was found in the TIA Portal project.");
                }

                report["attached_to_existing_tia"] = attachedToExisting;
                report["project_path"] = project.Path.FullName;
                report["plc_name"] = plcSoftware.Name;
                report["physical_download_executed"] = false;

                Dictionary<string, object> syncResult = SyncMap(plcSoftware, request);
                foreach (KeyValuePair<string, object> pair in syncResult)
                {
                    report[pair.Key] = pair.Value;
                }

                List<object> conflicts = report["conflicts"] as List<object>;
                report["status"] = (conflicts != null && conflicts.Count > 0)
                    ? "TIA_SYNC_COMPLETED_WITH_CONFLICTS"
                    : "TIA_SYNC_PASSED";
            }
            finally
            {
                if (!attachedToExisting && project != null)
                {
                    project.Close();
                }
                if (portal != null)
                {
                    portal.Dispose();
                }
            }
            return report;
        }

        private static Dictionary<string, object> SyncMap(PlcSoftware plcSoftware, Dictionary<string, object> request)
        {
            string tableName = GetString(request, "table_name", "PLC_Agent_IO");
            PlcTagTable table = plcSoftware.TagTableGroup.TagTables.Find(tableName);
            if (table == null)
            {
                table = plcSoftware.TagTableGroup.TagTables.Create(tableName);
            }

            object rawTags;
            IEnumerable tagItems = null;
            if (request.TryGetValue("tags", out rawTags))
            {
                tagItems = rawTags as IEnumerable;
            }
            if (tagItems == null)
            {
                throw new InvalidOperationException("The TIA request does not contain a valid tag collection.");
            }

            List<object> created = new List<object>();
            List<object> updated = new List<object>();
            List<string> unchanged = new List<string>();
            List<object> conflicts = new List<object>();
            HashSet<string> requestedNames = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            int requested = 0;

            foreach (object rawTag in tagItems)
            {
                Dictionary<string, object> tag = rawTag as Dictionary<string, object>;
                if (tag == null)
                {
                    continue;
                }
                requested++;
                string name = GetRequiredString(tag, "name");
                string dataType = GetString(tag, "data_type", "Bool");
                string address = GetRequiredString(tag, "address");
                requestedNames.Add(name);

                PlcTag existingTag = table.Tags.Find(name);
                if (existingTag == null)
                {
                    table.Tags.Create(name, dataType, address);
                    created.Add(new Dictionary<string, object> { { "name", name }, { "data_type", dataType }, { "address", address } });
                    continue;
                }

                bool sameType = String.Equals(existingTag.DataTypeName, dataType, StringComparison.OrdinalIgnoreCase);
                bool sameAddress = String.Equals(
                    NormalizeAddress(existingTag.LogicalAddress),
                    NormalizeAddress(address),
                    StringComparison.OrdinalIgnoreCase
                );
                if (!sameType || !sameAddress)
                {
                    conflicts.Add(new Dictionary<string, object>
                    {
                        { "name", name },
                        { "existing_data_type", existingTag.DataTypeName },
                        { "existing_address", existingTag.LogicalAddress },
                        { "requested_data_type", dataType },
                        { "requested_address", address }
                    });
                    continue;
                }
                unchanged.Add(name);
            }

            List<string> extraInTia = new List<string>();
            foreach (PlcTag existingTag in table.Tags)
            {
                if (!requestedNames.Contains(existingTag.Name))
                {
                    extraInTia.Add(existingTag.Name);
                }
            }

            return new Dictionary<string, object>
            {
                { "table", table.Name },
                { "requested", requested },
                { "created", created },
                { "updated", updated },
                { "unchanged", unchanged },
                { "conflicts", conflicts },
                { "extra_in_tia", extraInTia }
            };
        }

        private static Dictionary<string, object> ExecuteReadTags(Dictionary<string, object> request)
        {
            Dictionary<string, object> report = NewReport("RUNNING");
            string projectPath = GetString(request, "project_path", "");
            string requestedPlcName = GetString(request, "plc_name", "");
            bool attach = GetBool(request, "attach_to_running", true);
            bool withUi = GetBool(request, "with_user_interface", true);

            TiaPortal portal = null;
            Project project = null;
            bool attachedToExisting = false;
            try
            {
                if (attach)
                {
                    TiaPortalProcess process = TiaPortal.GetProcesses().FirstOrDefault();
                    if (process != null)
                    {
                        portal = process.Attach();
                        attachedToExisting = true;
                    }
                }
                if (portal == null)
                {
                    portal = new TiaPortal(withUi ? TiaPortalMode.WithUserInterface : TiaPortalMode.WithoutUserInterface);
                }

                project = portal.Projects.FirstOrDefault();
                if (project == null)
                {
                    if (String.IsNullOrWhiteSpace(projectPath) || !File.Exists(projectPath))
                    {
                        throw new FileNotFoundException("No TIA project is open and project_path is invalid.", projectPath);
                    }
                    project = portal.Projects.Open(new FileInfo(projectPath));
                }

                PlcSoftware plcSoftware = FindPlcSoftware(project, requestedPlcName);
                if (plcSoftware == null)
                {
                    throw new InvalidOperationException("No PLC software was found in the TIA Portal project.");
                }

                report["project_path"] = project.Path.FullName;
                report["plc_name"] = plcSoftware.Name;

                List<object> tagTables = new List<object>();
                int tagCount = 0;
                foreach (PlcTagTable table in plcSoftware.TagTableGroup.TagTables)
                {
                    List<object> tags = new List<object>();
                    foreach (PlcTag tag in table.Tags)
                    {
                        string comment = "";
                        try
                        {
                            comment = tag.Comment != null ? tag.Comment.ToString() : "";
                        }
                        catch (Exception)
                        {
                            comment = "";
                        }
                        tags.Add(new Dictionary<string, object>
                        {
                            { "name", tag.Name },
                            { "data_type", tag.DataTypeName },
                            { "address", tag.LogicalAddress },
                            { "comment", comment }
                        });
                        tagCount++;
                    }
                    tagTables.Add(new Dictionary<string, object> { { "table_name", table.Name }, { "tags", tags } });
                }
                report["tag_tables"] = tagTables;
                report["tag_count"] = tagCount;
                report["status"] = "TIA_READ_TAGS_PASSED";
            }
            finally
            {
                if (!attachedToExisting && project != null)
                {
                    project.Close();
                }
                if (portal != null)
                {
                    portal.Dispose();
                }
            }
            return report;
        }

        /// <summary>
        /// Downloads the already-compiled PLC software (blocks/program only, never hardware
        /// configuration) to the physical/target PLC configured in the current TIA project.
        /// Does NOT recompile, does NOT create/configure hardware, and NEVER guesses the
        /// download target: if the PLC or its online connection cannot be resolved to exactly
        /// one unambiguous candidate, it aborts without downloading.
        /// </summary>
        private static Dictionary<string, object> ExecuteDownload(Dictionary<string, object> request)
        {
            Dictionary<string, object> report = NewReport("RUNNING");
            string projectPath = GetString(request, "project_path", "");
            bool attach = GetBool(request, "attach_to_running", true);
            bool withUi = GetBool(request, "with_user_interface", true);

            TiaPortal portal = null;
            Project project = null;
            bool attachedToExisting = false;
            ExclusiveAccess downloadAccess=null;
            try
            {
                OpenConfiguredProject(request,out portal,out project,out attachedToExisting);

                if(GetString(request,"pid_project_mode","")=="NORMAL_PROJECT")
                {
                    downloadAccess=portal.ExclusiveAccess("Verificar y descargar PID Normal");
                    if(project.IsModified)throw new InvalidOperationException("PID_COMPILE_REQUIRED: el proyecto tiene cambios sin guardar.");
                    string checks=Path.Combine(Path.GetTempPath(),"normal_pid_download_"+Guid.NewGuid().ToString("N"));Directory.CreateDirectory(checks);
                    var normalPlc=FindPlcSoftware(project,GetString(request,"plc_name",""));
                    var state=ReadNormalState(request,project.Path.FullName,normalPlc,checks);
                    var manifest=request["pid_manifest"] as Dictionary<string,object>;
                    if(state==null || !state.ContainsKey("manifest"))throw new InvalidOperationException("PID_COMPILE_REQUIRED: falta el registro compilado del PID.");
                    PidControlSupport.ValidateNormalPidInventory(state,PidControlSupport.CaptureNormalPidInventory(normalPlc,manifest,project.Path.FullName,checks));
                }
                report["attached_to_existing_tia"] = attachedToExisting;
                report["project_path"] = project.Path.FullName;
                if(request.ContainsKey("pid_manifest"))
                {
                    var manifest=request["pid_manifest"] as Dictionary<string,object>;
                    PidControlSupport.VerifyDownloadTarget(manifest,GetString(request,"target_type",""));
                    var plc=FindPlcSoftware(project,GetString(request,"plc_name",""));
                    report["pid_pre_download"]=PidControlSupport.VerifyForDownload(plc,manifest);
                }
                RunDownload(project, request, report);
            }
            finally
            {
                if(downloadAccess!=null)downloadAccess.Dispose();
                if (!attachedToExisting && project != null)
                {
                    project.Close();
                }
                if (portal != null)
                {
                    portal.Dispose();
                }
            }
            return report;
        }

        /// <summary>
        /// Descarga del software ya compilado de `project` (compartido por la accion "download" y por
        /// "evaluate_trial", que descarga en la MISMA sesion la copia del ensayo ya archivada).
        /// Mismas guardias que siempre: PLC inequivoco, interfaz PLCSIM confirmada si
        /// require_simulation, configuraciones de descarga explicitas, nunca hardware salvo que se pida.
        /// </summary>
        private static void RunDownload(Project project, Dictionary<string, object> request, Dictionary<string, object> report)
        {
            string requestedPlcName = GetString(request, "plc_name", "");
            report["success"] = false;

            List<KeyValuePair<DeviceItem, PlcSoftware>> candidates = new List<KeyValuePair<DeviceItem, PlcSoftware>>();
            foreach (Device device in project.Devices)
            {
                foreach (DeviceItem item in device.DeviceItems)
                {
                    CollectPlcCandidates(item, candidates);
                }
            }

            List<KeyValuePair<DeviceItem, PlcSoftware>> matches = String.IsNullOrWhiteSpace(requestedPlcName)
                ? candidates
                : candidates.Where(c => String.Equals(c.Value.Name, requestedPlcName, StringComparison.OrdinalIgnoreCase)).ToList();

            if (matches.Count != 1)
            {
                report["status"] = "TIA_DOWNLOAD_AMBIGUOUS_TARGET";
                report["candidate_plc_names"] = candidates.Select(c => c.Value.Name).ToList();
                AddError(report, "No se pudo determinar de forma inequivoca el PLC objetivo del proyecto TIA.");
                return;
            }

            DeviceItem plcDeviceItem = matches[0].Key;
            PlcSoftware plcSoftware = matches[0].Value;
            report["plc_name"] = plcSoftware.Name;
            report["device_item_name"] = plcDeviceItem.Name;
            report["device_type"] = plcDeviceItem.TypeIdentifier;

            DownloadProvider downloadProvider = plcDeviceItem.GetService<DownloadProvider>();
            if (downloadProvider == null)
            {
                throw new InvalidOperationException("The target PLC device does not expose a download service.");
            }

            string targetType = GetString(request, "target_type", "PLCSIM_ADVANCED").Trim().ToUpperInvariant();
            bool requireSimulation = GetBool(request, "require_simulation", false);
            bool startModules = GetBool(request, "start_modules", true);
            string downloadScope = GetString(request, "download_scope", "SOFTWARE").Trim().ToUpperInvariant();
            report["target_type"] = targetType;
            report["target_name"] = GetString(request, "target_name", "");
            report["require_simulation"] = requireSimulation;
            report["download_scope"] = downloadScope;
            report["start_module_requested"] = false;
            report["start_module_configuration_seen"] = false;
            report["cpu_run_requested"] = false;
            report["cpu_run_confirmed"] = null;

            Log("[TIA DOWNLOAD] Target validation");
            if (requireSimulation && targetType != TargetTypePlcsimAdvanced)
            {
                report["status"] = "EXPERIMENT_TARGET_NOT_SIMULATION";
                AddError(report, "El destino configurado no es PLCSIM_ADVANCED (target_type=" + targetType + "). Modo Experimentacion nunca descarga a un PLC fisico.");
                return;
            }

            ConfigurationPcInterface pcInterface;
            IConfiguration targetConfiguration = ResolveDownloadTarget(downloadProvider.Configuration, request, targetType, report, out pcInterface);
            if (targetConfiguration == null)
            {
                report["status"] = "TIA_DOWNLOAD_AMBIGUOUS_TARGET";
                return;
            }

            // Guardia de simulacion (seccion 4): ademas de lo DECLARADO en la configuracion,
            // la interfaz PG/PC realmente resuelta en TIA debe ser la del simulador. Si no se
            // puede confirmar, se aborta sin descargar - nunca se adivina.
            string pcInterfaceName = pcInterface != null ? pcInterface.Name : "";
            bool simulatedInterface = pcInterfaceName.IndexOf("PLCSIM", StringComparison.OrdinalIgnoreCase) >= 0;
            report["simulation_interface_confirmed"] = simulatedInterface;
            if (requireSimulation && !simulatedInterface)
            {
                report["status"] = "EXPERIMENT_TARGET_NOT_SIMULATION";
                AddError(report, "La interfaz PG/PC resuelta ('" + pcInterfaceName + "') no corresponde a PLCSIM. Descarga experimental abortada.");
                return;
            }
            if (requireSimulation)
            {
                Log("[TIA DOWNLOAD] PLCSIM Advanced confirmed (" + pcInterfaceName + ")");
            }

            DownloadOptions options = downloadScope == "HARDWARE_AND_SOFTWARE"
                ? DownloadOptions.Hardware | DownloadOptions.Software
                : DownloadOptions.Software;

            List<object> handledConfigurations = new List<object>();
            report["download_configurations"] = handledConfigurations;
            DownloadConfigurationDelegate handler = configuration =>
                HandleDownloadConfiguration(configuration, targetType, startModules, handledConfigurations, report);

            Log("[TIA DOWNLOAD] Starting");
            DownloadResult downloadResult;
            try
            {
                string address=ConnectionTargetSupport.ValidateAddress(request);
                report["requested_target_address"]=address;
                if(address==null)
                    downloadResult=downloadProvider.Download(targetConfiguration,handler,handler,options);
                else
                {
                    var targetPort=targetConfiguration as ConfigurationTargetInterface;
                    if(targetPort==null)throw new InvalidOperationException("Seleccione un puerto del PLC para la direccion explicita.");
                    var endpoint=targetPort.Addresses.Find(address) ?? targetPort.Addresses.Create(address);
                    report["address_route_applied"]=true;
                    downloadResult=downloadProvider.Download(targetConfiguration,endpoint,handler,handler,options);
                }
            }
            catch (DownloadConfigurationRejectedException rejected)
            {
                report["status"] = "DOWNLOAD_CONFIGURATION_UNSUPPORTED";
                AddError(report, rejected.Message);
                return;
            }
            catch (Exception exception)
            {
                // Openness puede envolver la excepcion lanzada dentro del delegado.
                DownloadConfigurationRejectedException inner = FindInner<DownloadConfigurationRejectedException>(exception);
                if (inner != null)
                {
                    report["status"] = "DOWNLOAD_CONFIGURATION_UNSUPPORTED";
                    AddError(report, inner.Message);
                    return;
                }
                throw;
            }

            int errorCount = downloadResult.ErrorCount;
            int warningCount = downloadResult.WarningCount;
            bool success = errorCount == 0 && downloadResult.State != DownloadResultState.Error;

            report["download_state"] = downloadResult.State.ToString();
            report["download_error_count"] = errorCount;
            report["download_warning_count"] = warningCount;
            report["download_messages"] = FlattenDownloadMessages(downloadResult.Messages);
            report["success"] = success;
            report["download_success"] = success;
            bool startRequested = (bool)report["start_module_requested"];
            // Start Module solo se considera exitoso si TIA lo presento, se selecciono
            // StartModule y la descarga termino sin errores. Si TIA nunca presento
            // StartModules (la CPU no se detuvo), el resultado es "no aplica" (null), nunca
            // un exito inventado. cpu_run_confirmed queda null hasta tener Runtime API.
            report["start_module_success"] = startRequested ? (object)success : null;
            report["cpu_run_requested"] = startRequested && success;
            report["status"] = success ? "TIA_DOWNLOAD_PASSED" : "TIA_DOWNLOAD_FAILED";
            Log(success ? "[TIA DOWNLOAD] Download completed" : "[TIA DOWNLOAD] Download failed");
            if (startRequested && success)
            {
                Log("[TIA DOWNLOAD] Start module requested");
            }
            Log("[TIA DOWNLOAD] Completed");
        }

        private const string TargetTypePlcsimAdvanced = "PLCSIM_ADVANCED";

        private sealed class DownloadConfigurationRejectedException : InvalidOperationException
        {
            public DownloadConfigurationRejectedException(string message) : base(message)
            {
            }
        }

        // Politica explicita por tipo de DownloadConfiguration (nombres verificados por reflexion
        // contra Siemens.Engineering.dll V18). Valor = seleccion a aplicar ("" = el tipo no expone
        // seleccion, solo se permite continuar). Cualquier tipo ausente se RECHAZA: nunca se acepta
        // silenciosamente una configuracion desconocida (seccion 7).
        private static readonly Dictionary<string, string> PlcsimAllowedConfigurations = new Dictionary<string, string>(StringComparer.Ordinal)
        {
            { "StopModules", "StopAll" },
            { "StartModules", "StartModule" },
            { "ConsistentBlocksDownload", "ConsistentDownload" },
            { "AlarmTextLibrariesDownload", "ConsistentDownload" },
            { "AllBlocksDownload", "DownloadAllBlocks" },
            { "DataBlockReinitialization", "StopPlcAndReinitialize" },
            { "OverwriteSystemData", "Overwrite" },
            { "LoadIdentificationData", "LoadNothing" },
            { "WaitOnReboot", "Wait" },
            { "DownloadCertificate", "" }
        };

        // PLC fisico: solo lo imprescindible para cargar software; nada que reinicialice datos,
        // sobrescriba configuracion de sistema o acepte certificados automaticamente.
        private static readonly Dictionary<string, string> PhysicalAllowedConfigurations = new Dictionary<string, string>(StringComparer.Ordinal)
        {
            { "StopModules", "StopAll" },
            { "StartModules", "StartModule" },
            { "ConsistentBlocksDownload", "ConsistentDownload" },
            { "AlarmTextLibrariesDownload", "ConsistentDownload" },
            { "AllBlocksDownload", "DownloadAllBlocks" },
            { "LoadIdentificationData", "LoadNothing" }
        };

        /// <summary>
        /// Pure decision (no Siemens API): which selection to apply to a DownloadConfiguration
        /// type for a given target, or null + allowed=false if it must abort the download.
        /// </summary>
        private static string DecideDownloadConfiguration(string typeName, string targetType, bool startModules, out bool allowed)
        {
            if (typeName == "StartModules" && !startModules)
            {
                allowed = true;
                return "NoAction";
            }
            Dictionary<string, string> policy = targetType == TargetTypePlcsimAdvanced
                ? PlcsimAllowedConfigurations
                : PhysicalAllowedConfigurations;
            string selection;
            allowed = policy.TryGetValue(typeName, out selection);
            return allowed ? selection : null;
        }

        private static void HandleDownloadConfiguration(
            DownloadConfiguration configuration,
            string targetType,
            bool startModules,
            List<object> handledConfigurations,
            Dictionary<string, object> report)
        {
            string typeName = configuration.GetType().Name;
            bool allowed;
            string selection = DecideDownloadConfiguration(typeName, targetType, startModules, out allowed);
            handledConfigurations.Add(new Dictionary<string, object>
            {
                { "type", typeName },
                { "message", configuration.Message },
                { "selection", selection },
                { "allowed", allowed }
            });
            if (!allowed)
            {
                Log("[TIA DOWNLOAD] Unsupported configuration: " + typeName);
                throw new DownloadConfigurationRejectedException(
                    "Configuracion de descarga no soportada para " + targetType + ": " + typeName
                    + " (" + configuration.Message + "). Descarga abortada."
                );
            }
            if (!String.IsNullOrEmpty(selection))
            {
                PropertyInfo selectionProperty = configuration.GetType().GetProperty("CurrentSelection");
                if (selectionProperty == null)
                {
                    throw new DownloadConfigurationRejectedException(
                        "La configuracion " + typeName + " no expone CurrentSelection; no se puede aplicar '" + selection + "'."
                    );
                }
                selectionProperty.SetValue(configuration, Enum.Parse(selectionProperty.PropertyType, selection), null);
            }
            if (typeName == "StartModules")
            {
                report["start_module_configuration_seen"] = true;
                report["start_module_requested"] = selection == "StartModule";
            }
            Log("[TIA DOWNLOAD] Configuration " + typeName + " -> " + (String.IsNullOrEmpty(selection) ? "(continuar, sin seleccion)" : selection));
        }

        private static T FindInner<T>(Exception exception) where T : Exception
        {
            while (exception != null)
            {
                T match = exception as T;
                if (match != null)
                {
                    return match;
                }
                exception = exception.InnerException;
            }
            return null;
        }

        /// <summary>
        /// Selects Mode -> PC interface -> target interface by the names configured in the request
        /// (configuration_mode / pc_interface / target_interface). With no pc_interface configured,
        /// a PLCSIM_ADVANCED target auto-selects the single PC interface whose name contains
        /// "PLCSIM"; any other target requires exactly one PC interface overall. Never scans the
        /// network, never changes addresses, never picks among several candidates.
        /// </summary>
        private static List<Dictionary<string,object>> ConnectionRows(ConnectionConfiguration configuration)
        {
            var rows=new List<Dictionary<string,object>>();
            foreach(var mode in configuration.Modes)
                foreach(var pc in mode.PcInterfaces)
                    rows.Add(new Dictionary<string,object>{{"mode",mode.Name},{"pc_interface",pc.Name},
                        {"number",pc.Number},{"target_interfaces",pc.TargetInterfaces.Select(t=>t.Name).ToList()}});
            return rows;
        }

        private static Dictionary<string,object> ExecuteListConnections(Dictionary<string,object> request)
        {
            var report=NewReport("TIA_CONNECTIONS_FAILED");TiaPortal portal=null;Project project=null;bool attached=false;
            try
            {
                OpenConfiguredProject(request,out portal,out project,out attached);
                report["project_path"]=project.Path.FullName;
                var cpus=new List<KeyValuePair<DeviceItem,PlcSoftware>>();
                foreach(Device device in project.Devices)
                    foreach(DeviceItem item in device.DeviceItems)CollectPlcCandidates(item,cpus);
                report["expected_cpus"]=cpus.Select(c=>new Dictionary<string,object>{{"plc_name",c.Value.Name},{"name",c.Key.Name},{"type_identifier",c.Key.TypeIdentifier}}).ToList();
                string name=GetString(request,"plc_name","");
                var matches=String.IsNullOrWhiteSpace(name)?cpus:cpus.Where(c=>String.Equals(c.Value.Name,name,StringComparison.OrdinalIgnoreCase)).ToList();
                if(matches.Count!=1)throw new InvalidOperationException("Seleccione una CPU unica en el proyecto Normal.");
                var provider=matches[0].Key.GetService<DownloadProvider>();
                if(provider==null)throw new InvalidOperationException("La CPU seleccionada no ofrece el servicio de descarga.");
                report["connections"]=ConnectionRows(provider.Configuration);
                report["capabilities"]=new Dictionary<string,object>{{"physical_discovery",false},{"explicit_address",true}};
                report["status"]="TIA_CONNECTIONS_PASSED";report["physical_download_executed"]=false;
            }
            finally {if(project!=null && !attached)project.Close();if(portal!=null)portal.Dispose();}
            return report;
        }

        private static IConfiguration ResolveDownloadTarget(ConnectionConfiguration connectionConfiguration,
            Dictionary<string,object> request,string targetType,Dictionary<string,object> report,out ConfigurationPcInterface pcInterface)
        {
            pcInterface=null;var rows=ConnectionRows(connectionConfiguration);report["available_connections"]=rows;
            var selection=new Dictionary<string,object>(request);selection["target_type"]=targetType;
            Dictionary<string,object> selected;
            try {selected=ConnectionTargetSupport.SelectInterface(rows,selection);ConnectionTargetSupport.ValidateAddress(request);}
            catch(InvalidOperationException error){AddError(report,error.Message);return null;}
            var mode=connectionConfiguration.Modes.Find(Convert.ToString(selected["mode"]));
            pcInterface=mode.PcInterfaces.Find(Convert.ToString(selected["pc_interface"]),Convert.ToInt32(selected["number"]));
            report["configuration_mode"]=mode.Name;report["pc_interface_name"]=pcInterface.Name;report["pc_interface_number"]=pcInterface.Number;
            var targets=pcInterface.TargetInterfaces.ToList();string name=GetString(request,"target_interface","").Trim();
            var matches=name.Length==0?targets:targets.Where(t=>String.Equals(t.Name,name,StringComparison.OrdinalIgnoreCase)).ToList();
            if(matches.Count!=1){report["available_target_interfaces"]=targets.Select(t=>t.Name).ToList();AddError(report,"Seleccione un puerto destino inequivoco del proyecto.");return null;}
            report["target_interface_name"]=matches[0].Name;return matches[0];
        }

        private static void CollectPlcCandidates(DeviceItem item, IList<KeyValuePair<DeviceItem, PlcSoftware>> result)
        {
            SoftwareContainer container = item.GetService<SoftwareContainer>();
            if (container != null && container.Software is PlcSoftware)
            {
                result.Add(new KeyValuePair<DeviceItem, PlcSoftware>(item, (PlcSoftware)container.Software));
            }
            foreach (DeviceItem child in item.DeviceItems)
            {
                CollectPlcCandidates(child, result);
            }
        }

        private static List<Dictionary<string, object>> FlattenDownloadMessages(DownloadResultMessageComposition messages)
        {
            List<Dictionary<string, object>> output = new List<Dictionary<string, object>>();
            foreach (DownloadResultMessage message in messages)
            {
                AddDownloadMessage(message, output);
            }
            return output;
        }

        private static void AddDownloadMessage(DownloadResultMessage message, IList<Dictionary<string, object>> output)
        {
            output.Add(new Dictionary<string, object>
            {
                { "state", message.State.ToString() },
                { "message", message.Message },
                { "error_count", message.ErrorCount },
                { "warning_count", message.WarningCount },
                { "date_time", message.DateTime.ToString("s") }
            });
            foreach (DownloadResultMessage child in message.Messages)
            {
                AddDownloadMessage(child, output);
            }
        }

        private static List<Dictionary<string, object>> FlattenMessages(CompilerResultMessageComposition messages)
        {
            List<Dictionary<string, object>> output = new List<Dictionary<string, object>>();
            foreach (CompilerResultMessage message in messages)
            {
                AddCompilerMessage(message, output);
            }
            return output;
        }

        private static void AddCompilerMessage(CompilerResultMessage message, IList<Dictionary<string, object>> output)
        {
            output.Add(new Dictionary<string, object>
            {
                { "state", message.State.ToString() },
                { "description", message.Description },
                { "path", message.Path },
                { "error_count", message.ErrorCount },
                { "warning_count", message.WarningCount }
            });
            foreach (CompilerResultMessage child in message.Messages)
            {
                AddCompilerMessage(child, output);
            }
        }


        // =====================================================================================
        // Fase 4A-DEFERRED: TIA MASTER + evaluacion diferida de un ensayo guardado
        // =====================================================================================

        private static string Sha256File(string path)
        {
            using (System.Security.Cryptography.SHA256 sha = System.Security.Cryptography.SHA256.Create())
            using (FileStream stream = File.OpenRead(path))
            {
                return BitConverter.ToString(sha.ComputeHash(stream)).Replace("-", "").ToLowerInvariant();
            }
        }

        private static List<string> GetStringList(Dictionary<string, object> payload, string key)
        {
            List<string> result = new List<string>();
            object raw;
            if (payload.TryGetValue(key, out raw) && raw is IEnumerable && !(raw is string))
            {
                foreach (object item in (IEnumerable)raw)
                {
                    if (item != null)
                    {
                        result.Add(item.ToString());
                    }
                }
            }
            return result;
        }

        private static void CollectBlocks(PlcBlockGroup group, string path, List<Dictionary<string, object>> result)
        {
            foreach (PlcBlock block in group.Blocks)
            {
                string language = "";
                try
                {
                    language = block.ProgrammingLanguage.ToString();
                }
                catch (Exception)
                {
                    language = "";
                }
                result.Add(new Dictionary<string, object>
                {
                    { "name", block.Name },
                    { "number", block.Number },
                    { "type", block.GetType().Name },
                    { "language", language },
                    { "group", path }
                });
            }
            foreach (PlcBlockUserGroup child in group.Groups)
            {
                CollectBlocks(child, path + "/" + child.Name, result);
            }
        }

        private static List<Dictionary<string, object>> ListBlockNames(PlcBlockGroup group, string path)
        {
            List<Dictionary<string, object>> result = new List<Dictionary<string, object>>();
            foreach (PlcBlock block in group.Blocks)
            {
                result.Add(new Dictionary<string, object> { { "name", block.Name }, { "type", block.GetType().Name }, { "group", path } });
            }
            foreach (PlcBlockUserGroup child in group.Groups)
            {
                result.AddRange(ListBlockNames(child, path + "/" + child.Name));
            }
            return result;
        }

        private static PlcBlock FindBlock(PlcBlockGroup group, string name)
        {
            PlcBlock found = group.Blocks.Find(name);
            if (found != null)
            {
                return found;
            }
            foreach (PlcBlockUserGroup child in group.Groups)
            {
                found = FindBlock(child, name);
                if (found != null)
                {
                    return found;
                }
            }
            return null;
        }

        private static List<Dictionary<string, object>> DescribeInterfaces(Project project)
        {
            List<Dictionary<string, object>> interfaces = new List<Dictionary<string, object>>();
            foreach (Device device in project.Devices)
            {
                foreach (DeviceItem item in device.DeviceItems)
                {
                    CollectInterfaces(item, interfaces);
                }
            }
            return interfaces;
        }

        private static void CollectInterfaces(DeviceItem item, List<Dictionary<string, object>> result)
        {
            NetworkInterface networkInterface = item.GetService<NetworkInterface>();
            if (networkInterface != null)
            {
                List<Dictionary<string, object>> nodes = new List<Dictionary<string, object>>();
                foreach (Node node in networkInterface.Nodes)
                {
                    object address = null;
                    try
                    {
                        address = node.GetAttribute("Address");
                    }
                    catch (Exception)
                    {
                        address = null;
                    }
                    nodes.Add(new Dictionary<string, object>
                    {
                        { "name", node.Name },
                        { "type", node.NodeType.ToString() },
                        { "address", address == null ? "" : address.ToString() }
                    });
                }
                result.Add(new Dictionary<string, object>
                {
                    { "device_item", item.Name },
                    { "interface_type", networkInterface.InterfaceType.ToString() },
                    { "nodes", nodes }
                });
            }
            foreach (DeviceItem child in item.DeviceItems)
            {
                CollectInterfaces(child, result);
            }
        }

        private static Dictionary<string, object> DescribeCpuIdentity(Project project,string requestedPlcName)
        {
            var candidates=new List<KeyValuePair<DeviceItem,PlcSoftware>>();
            foreach(Device device in project.Devices)
                foreach(DeviceItem item in device.DeviceItems)CollectPlcCandidates(item,candidates);
            var matches=String.IsNullOrWhiteSpace(requestedPlcName)?candidates:
                candidates.Where(c=>String.Equals(c.Value.Name,requestedPlcName,StringComparison.OrdinalIgnoreCase)).ToList();
            var info=new Dictionary<string,object>{{"project_name",project.Name},{"plc_count",candidates.Count}};
            if(matches.Count!=1)throw new InvalidOperationException("PID_CPU_IDENTITY: no unique CPU in the compiled copy");
            info["plc_name"]=matches[0].Value.Name;
            info["cpu_device_item"]=matches[0].Key.Name;
            info["cpu_type_identifier"]=matches[0].Key.TypeIdentifier;
            foreach(string attribute in new[]{"TypeName","OrderNumber","FirmwareVersion"})
            {
                object value=null;try{value=matches[0].Key.GetAttribute(attribute);}catch(Exception){}
                info["cpu_"+attribute]=value==null?null:value.ToString();
            }
            return info;
        }

        private static Dictionary<string, object> DescribePlcProject(Project project, string requestedPlcName)
        {
            List<KeyValuePair<DeviceItem, PlcSoftware>> candidates = new List<KeyValuePair<DeviceItem, PlcSoftware>>();
            foreach (Device device in project.Devices)
            {
                foreach (DeviceItem item in device.DeviceItems)
                {
                    CollectPlcCandidates(item, candidates);
                }
            }
            Dictionary<string, object> info = new Dictionary<string, object>
            {
                { "project_name", project.Name },
                { "project_version", project.Version },
                { "plc_count", candidates.Count },
                { "plc_names", candidates.Select(c => c.Value.Name).ToList() },
                { "interfaces", DescribeInterfaces(project) }
            };
            List<KeyValuePair<DeviceItem, PlcSoftware>> matches = String.IsNullOrWhiteSpace(requestedPlcName)
                ? candidates
                : candidates.Where(c => String.Equals(c.Value.Name, requestedPlcName, StringComparison.OrdinalIgnoreCase)).ToList();
            if (matches.Count == 1)
            {
                PlcSoftware plcSoftware = matches[0].Value;
                info["plc_name"] = plcSoftware.Name;
                info["cpu_device_item"] = matches[0].Key.Name;
                info["cpu_type_identifier"] = matches[0].Key.TypeIdentifier;
                // Atributos de catalogo (best-effort): si TIA no los expone, quedan null (nunca se inventan).
                foreach (string attribute in new[] { "TypeName", "OrderNumber", "FirmwareVersion" })
                {
                    object value = null;
                    try
                    {
                        value = matches[0].Key.GetAttribute(attribute);
                    }
                    catch (Exception)
                    {
                        value = null;
                    }
                    info["cpu_" + attribute] = value == null ? null : value.ToString();
                }
                List<Dictionary<string, object>> blocks = new List<Dictionary<string, object>>();
                CollectBlocks(plcSoftware.BlockGroup, "", blocks);
                info["blocks"] = blocks;
                info["tag_tables"] = plcSoftware.TagTableGroup.TagTables.Select(t => t.Name).ToList();
                info["plc_agent_io_present"] = plcSoftware.TagTableGroup.TagTables.Find("PLC_Agent_IO") != null;
                info["external_sources"] = plcSoftware.ExternalSourceGroup.ExternalSources.Select(e => e.Name).ToList();
            }
            return info;
        }

        private const string ZapExtension = ".zap18";

        /// <summary>
        /// Project.Archive usa targetName LITERALMENTE como nombre del archivo creado (verificado con TIA
        /// V18 real: sin extension se crea un ZIP sin extension). Por eso el nombre se construye siempre
        /// explicito con ".zap18" y la ruta esperada es exactamente targetDirectory\targetName.
        /// </summary>
        private static string ArchiveTargetName(string requestedName)
        {
            string name = Path.GetFileName(requestedName ?? "");
            if (String.IsNullOrWhiteSpace(name))
            {
                throw new ArgumentException("archive name is empty");
            }
            return name.EndsWith(ZapExtension, StringComparison.OrdinalIgnoreCase) ? name : name + ZapExtension;
        }

        /// <summary>
        /// Archive comprimido con nombre explicito .zap18 y verificacion EXACTA del archivo esperado
        /// (existe, tamano > 0, SHA-256). Nunca busca "otro" archivo parecido: si TIA crea algo con otro
        /// nombre se informa como NOT_CREATED con la lista de archivos realmente creados.
        /// Devuelve el codigo de resultado ("CREATED" o el codigo de error) y rellena `report`.
        /// </summary>
        /// <summary>Dobles de prueba del self_test: mismo nombre de tipo que la excepcion real de Openness.</summary>
        private static class SelfTestFakes
        {
            internal sealed class EngineeringTargetInvocationException : Exception
            {
                internal EngineeringTargetInvocationException(string message) : base(message) { }
            }
        }

        private static readonly byte[] SelfTestZipBytes =
        {
            0x50, 0x4B, 0x03, 0x04, 0x0A, 0x00, 0x00, 0x00,
            0x50, 0x4B, 0x05, 0x06, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0
        };

        /// <summary>
        /// Escenarios de ArchiveWithRetry sin TIA (accion de Archive simulada, sin esperas reales). Cada
        /// escenario anade un check {"archive_scenario", status, attempt_count, recovered, calls, sleeps,
        /// attempt_statuses, transient_flags, target_after_failure, files, passed}.
        /// </summary>
        private static void RunArchiveRetrySelfTest(Dictionary<string, object> report, List<object> checks)
        {
            string root = Path.Combine(Path.GetTempPath(), "tia_archive_selftest_" + Guid.NewGuid().ToString("N"));
            const string transientMessage = "Error when calling method 'Archive' of type 'Siemens.Engineering.Project'.\r\n\r\n"
                + "Unable to archive the project.\r\n\r\nArchiving failed.\r\nCould not find file 'C:\\x\\T0001.zap18'.";
            try
            {
                // steps: "ok" (escribe ZIP completo), "transient", "transient_partial" (deja destino truncado),
                // "transient_complete" (deja ZIP completo), "other" (ETIE con otro mensaje), "io" (IOException
                // con el mismo texto: tipo distinto -> no transitorio). preexisting: destino creado antes.
                Func<string, string[], bool, Dictionary<string, object>> run = (name, steps, preexisting) =>
                {
                    string directory = Path.Combine(root, name);
                    Directory.CreateDirectory(directory);
                    string target = Path.Combine(directory, "T0001.zap18");
                    if (preexisting)
                    {
                        File.WriteAllBytes(target, SelfTestZipBytes);
                    }
                    int calls = 0;
                    List<int> sleeps = new List<int>();
                    Dictionary<string, object> scenarioReport = new Dictionary<string, object>();
                    Action archive = () =>
                    {
                        string step = steps[Math.Min(calls, steps.Length - 1)];
                        calls++;
                        if (step == "ok")
                        {
                            File.WriteAllBytes(target, SelfTestZipBytes);
                            return;
                        }
                        if (step == "transient_partial")
                        {
                            File.WriteAllBytes(target, new byte[] { 0x50, 0x4B, 0x03, 0x04, 0x01 });
                        }
                        if (step == "transient_complete")
                        {
                            File.WriteAllBytes(target, SelfTestZipBytes);
                        }
                        if (step == "other")
                        {
                            throw new SelfTestFakes.EngineeringTargetInvocationException("Unable to archive the project. Access denied.");
                        }
                        if (step == "io")
                        {
                            throw new IOException("Could not find file 'C:\\x\\T0001.zap18'.");
                        }
                        throw new SelfTestFakes.EngineeringTargetInvocationException(transientMessage);
                    };
                    string status = ArchiveWithRetry(archive, directory, target, TrialArchiveMaxAttempts, ArchiveRetryBackoffMs,
                        milliseconds => sleeps.Add(milliseconds), scenarioReport, "TRIAL");
                    List<object> attemptList = (List<object>)scenarioReport["archive_attempts"];
                    return new Dictionary<string, object>
                    {
                        { "archive_scenario", name },
                        { "status", status },
                        { "attempt_count", scenarioReport["archive_attempt_count"] },
                        { "recovered", scenarioReport["archive_recovered_after_retry"] },
                        { "calls", calls },
                        { "sleeps", sleeps },
                        { "attempt_statuses", attemptList.Select(a => ((Dictionary<string, object>)a)["status"]).ToList() },
                        { "transient_flags", attemptList.Select(a => ((Dictionary<string, object>)a)["transient"]).ToList() },
                        { "target_after_failure", attemptList.Select(a => ((Dictionary<string, object>)a).ContainsKey("target_after_failure")
                            ? ((Dictionary<string, object>)a)["target_after_failure"] : null).ToList() },
                        { "attempt_fields_complete", attemptList.All(a => new[] { "attempt_number", "started_at", "completed_at", "duration_ms",
                            "status", "exception_type", "error_message", "transient" }.All(((Dictionary<string, object>)a).ContainsKey)) },
                        { "sha256", scenarioReport.ContainsKey("archive_sha256") ? scenarioReport["archive_sha256"] : null },
                        { "error_kept", scenarioReport.ContainsKey("archive_error") },
                        { "files", Directory.GetFiles(directory).Select(Path.GetFileName).OrderBy(f => f).ToList() }
                    };
                };

                Action<Dictionary<string, object>, string, int, int, bool> expect = (result, expectedStatus, expectedAttempts, expectedCalls, expectedRecovered) =>
                {
                    bool passed = (string)result["status"] == expectedStatus && (int)result["attempt_count"] == expectedAttempts
                        && (int)result["calls"] == expectedCalls && (bool)result["recovered"] == expectedRecovered
                        && (bool)result["attempt_fields_complete"];
                    result["passed"] = passed;
                    checks.Add(result);
                    if (!passed)
                    {
                        AddError(report, "ArchiveWithRetry[" + result["archive_scenario"] + "]: status=" + result["status"]
                            + " attempts=" + result["attempt_count"] + " calls=" + result["calls"] + " recovered=" + result["recovered"]);
                    }
                };

                expect(run("pass_first", new[] { "ok" }, false), "CREATED", 1, 1, false);
                expect(run("transient_then_pass", new[] { "transient", "ok" }, false), "CREATED", 2, 2, true);
                expect(run("two_transient_then_pass", new[] { "transient", "transient", "ok" }, false), "CREATED", 3, 3, true);
                expect(run("three_transient", new[] { "transient", "transient", "transient", "ok" }, false), "TRIAL_ARCHIVE_FAILED", 3, 3, false);
                expect(run("other_error_no_retry", new[] { "other", "ok" }, false), "TRIAL_ARCHIVE_FAILED", 1, 1, false);
                expect(run("io_exception_no_retry", new[] { "io", "ok" }, false), "TRIAL_ARCHIVE_FAILED", 1, 1, false);
                expect(run("partial_target_quarantined", new[] { "transient_partial", "ok" }, false), "CREATED", 2, 2, true);
                expect(run("complete_target_kept", new[] { "transient_complete", "ok" }, false), "TRIAL_ARCHIVE_FAILED", 1, 1, false);
                expect(run("preexisting_target", new[] { "ok" }, true), "TRIAL_ARCHIVE_FAILED", 0, 0, false);
            }
            finally
            {
                try
                {
                    Directory.Delete(root, true);
                }
                catch (Exception)
                {
                    // Solo es la carpeta temporal del self_test: si no se puede borrar no afecta al resultado.
                }
            }
        }

        // Politica de reintento de Project.Archive (solo ensayos; el MASTER sigue con un unico intento).
        // Causa manejada: carrera interna de TIA V18 entre Archive (que copia el proyecto a
        // %TEMP%\#TempArchive_<pid>\<nombre>.zap18 antes de comprimir) y el indexador de busqueda que
        // reescribe IM/SearchIndex tras Save -> EngineeringTargetInvocationException "Could not find file".
        internal const int TrialArchiveMaxAttempts = 3;
        internal const int TrialArchiveSettleMs = 2000;                    // espera fija entre Save y el 1er Archive
        internal static readonly int[] ArchiveRetryBackoffMs = { 2000, 3000 }; // antes del 2do y del 3er intento
        internal const string TransientArchiveMarker = "Could not find file";

        /// <summary>
        /// Unico error de Archive que se reintenta: EngineeringTargetInvocationException cuyo mensaje (o el de
        /// una excepcion interna) contiene "Could not find file". Cualquier otro error falla sin reintento.
        /// </summary>
        internal static bool IsTransientArchiveError(Exception exception)
        {
            if (exception == null || exception.GetType().Name != "EngineeringTargetInvocationException")
            {
                return false;
            }
            for (Exception current = exception; current != null; current = current.InnerException)
            {
                if ((current.Message ?? "").IndexOf(TransientArchiveMarker, StringComparison.OrdinalIgnoreCase) >= 0)
                {
                    return true;
                }
            }
            return false;
        }

        /// <summary>
        /// ZIP estructuralmente completo: firma local "PK\x03\x04" al inicio y registro de fin de directorio
        /// central "PK\x05\x06" en la cola. Un .zap18 truncado por un Archive abortado no lo cumple.
        /// </summary>
        internal static bool LooksLikeCompleteZip(string path)
        {
            try
            {
                using (FileStream stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read))
                {
                    if (stream.Length < 22)
                    {
                        return false;
                    }
                    byte[] head = new byte[4];
                    if (stream.Read(head, 0, 4) != 4 || head[0] != 0x50 || head[1] != 0x4B || head[2] != 0x03 || head[3] != 0x04)
                    {
                        return false;
                    }
                    int tailLength = (int)Math.Min(stream.Length, 22 + 65535);
                    byte[] tail = new byte[tailLength];
                    stream.Seek(-tailLength, SeekOrigin.End);
                    int read = 0;
                    while (read < tailLength)
                    {
                        int chunk = stream.Read(tail, read, tailLength - read);
                        if (chunk <= 0)
                        {
                            return false;
                        }
                        read += chunk;
                    }
                    for (int index = tailLength - 22; index >= 0; index--)
                    {
                        if (tail[index] == 0x50 && tail[index + 1] == 0x4B && tail[index + 2] == 0x05 && tail[index + 3] == 0x06)
                        {
                            return true;
                        }
                    }
                    return false;
                }
            }
            catch (IOException)
            {
                return false;
            }
        }

        private static string ArchiveProject(Project project, string targetDirectory, string requestedName, Dictionary<string, object> report,
            string errorPrefix, int maxAttempts = 1)
        {
            string targetName = ArchiveTargetName(requestedName);
            string expectedPath = Path.Combine(targetDirectory, targetName);
            report["archive_source_project"] = project.Path.FullName;
            report["archive_target_directory"] = targetDirectory;
            report["archive_target_name"] = targetName;
            report["archive_expected_path"] = expectedPath;
            report["archive_mode"] = ProjectArchivationMode.Compressed.ToString();
            Log("[TIA ARCHIVE] source=" + project.Path.FullName + " target_dir=" + targetDirectory + " target_name=" + targetName
                + " expected=" + expectedPath + " mode=" + ProjectArchivationMode.Compressed + " max_attempts=" + maxAttempts);
            // Cada intento: MISMA sesion TIA, MISMO proyecto ya guardado y compilado, MISMO destino. Nunca se recompila.
            return ArchiveWithRetry(
                () => project.Archive(new DirectoryInfo(targetDirectory), targetName, ProjectArchivationMode.Compressed),
                targetDirectory, expectedPath, maxAttempts, ArchiveRetryBackoffMs,
                milliseconds => System.Threading.Thread.Sleep(milliseconds), report, errorPrefix);
        }

        /// <summary>
        /// Motor de reintento de Archive (inyectable: lo ejercita self_test sin TIA). Reglas:
        ///  - destino existente ANTES del primer intento -> error, nunca se sobrescribe ni se llama a Archive;
        ///  - solo se reintenta un error transitorio (IsTransientArchiveError), hasta maxAttempts en total,
        ///    esperando backoffMs[n-1] antes del intento n+1;
        ///  - si tras un fallo quedo un destino: ZIP completo -> se conserva intacto y NO se reintenta (no se
        ///    sobrescribe); parcial/corrupto -> se renombra a "<destino>.partial_attemptN" (nunca se borra);
        ///  - cada intento queda en report["archive_attempts"] (attempt_number, started_at, completed_at,
        ///    duration_ms, status, exception_type, error_message, transient).
        /// </summary>
        internal static string ArchiveWithRetry(Action archiveCall, string targetDirectory, string expectedPath, int maxAttempts,
            int[] backoffMs, Action<int> sleep, Dictionary<string, object> report, string errorPrefix)
        {
            maxAttempts = Math.Max(1, maxAttempts);
            List<object> attempts = new List<object>();
            report["archive_attempts"] = attempts;
            report["archive_attempt_count"] = 0;
            report["archive_max_attempts"] = maxAttempts;
            report["archive_retry_backoff_ms"] = backoffMs;
            report["archive_recovered_after_retry"] = false;

            Directory.CreateDirectory(targetDirectory);
            if (File.Exists(expectedPath))
            {
                report["archive_error"] = "El archivo destino ya existe (nunca se sobrescribe): " + expectedPath;
                return errorPrefix + "_ARCHIVE_FAILED";
            }
            HashSet<string> before = new HashSet<string>(Directory.GetFiles(targetDirectory), StringComparer.OrdinalIgnoreCase);

            for (int attemptNumber = 1; attemptNumber <= maxAttempts; attemptNumber++)
            {
                Checkpoint("archive_attempt", attemptNumber + "/" + maxAttempts);
                DateTime startedAt = DateTime.Now;
                System.Diagnostics.Stopwatch watch = System.Diagnostics.Stopwatch.StartNew();
                Exception failure = null;
                try
                {
                    archiveCall();
                }
                catch (Exception exception)
                {
                    failure = exception;
                }
                watch.Stop();
                Dictionary<string, object> attempt = new Dictionary<string, object>
                {
                    { "attempt_number", attemptNumber },
                    { "started_at", startedAt.ToString("yyyy-MM-ddTHH:mm:ss.fff") },
                    { "completed_at", DateTime.Now.ToString("yyyy-MM-ddTHH:mm:ss.fff") },
                    { "duration_ms", (long)watch.ElapsedMilliseconds },
                    { "status", failure == null ? "CREATED" : "FAILED" },
                    { "exception_type", failure == null ? null : failure.GetType().FullName },
                    { "error_message", failure == null ? null : failure.Message },
                    { "transient", failure != null && IsTransientArchiveError(failure) }
                };
                attempts.Add(attempt);
                report["archive_attempt_count"] = attemptNumber;

                if (failure == null)
                {
                    List<string> created = Directory.GetFiles(targetDirectory).Where(f => !before.Contains(f)).Select(Path.GetFileName).ToList();
                    report["archive_actual_files_created"] = created;
                    if (!File.Exists(expectedPath))
                    {
                        attempt["status"] = "NOT_CREATED";
                        report["archive_error"] = "Project.Archive no creo el archivo esperado " + expectedPath;
                        return errorPrefix + "_ARCHIVE_NOT_CREATED";
                    }
                    long size = new FileInfo(expectedPath).Length;
                    report["archive_size_bytes"] = size;
                    if (size <= 0)
                    {
                        attempt["status"] = "EMPTY";
                        report["archive_error"] = "El archivo creado esta vacio: " + expectedPath;
                        return errorPrefix + "_ARCHIVE_EMPTY";
                    }
                    // Los errores de intentos anteriores quedan SOLO en archive_attempts: el archivado termino bien.
                    report.Remove("archive_error");
                    report.Remove("archive_error_type");
                    report.Remove("archive_error_hint");
                    report["archive_recovered_after_retry"] = attemptNumber > 1;
                    report["archive_path"] = expectedPath;
                    report["archive_sha256"] = Sha256File(expectedPath);
                    return "CREATED";
                }

                bool transient = (bool)attempt["transient"];
                report["archive_error_type"] = failure.GetType().FullName;
                report["archive_error"] = failure.Message;
                if (failure.GetType().Name == "EngineeringTargetInvocationException")
                {
                    report["archive_error_hint"] = transient
                        ? "Error transitorio de TIA (carrera con IM/SearchIndex durante Archive)."
                        : "TIA rechazo el archivado; el motivo exacto esta en archive_error.";
                }
                Checkpoint("archive_attempt_error", attemptNumber + "/" + maxAttempts + " transient=" + transient + " "
                    + failure.GetType().Name + ": " + failure.Message);

                if (File.Exists(expectedPath))
                {
                    if (LooksLikeCompleteZip(expectedPath))
                    {
                        // Archive lanzo excepcion pero dejo un ZIP completo: se conserva tal cual y no se reintenta.
                        attempt["target_after_failure"] = "COMPLETE_KEPT";
                        report["archive_error"] = failure.Message + " | Quedo un destino con ZIP completo tras la excepcion; "
                            + "se conserva sin sobrescribir y no se reintenta: " + expectedPath;
                        return errorPrefix + "_ARCHIVE_FAILED";
                    }
                    string quarantine = expectedPath + ".partial_attempt" + attemptNumber;
                    File.Move(expectedPath, quarantine);
                    attempt["target_after_failure"] = "PARTIAL_QUARANTINED";
                    attempt["quarantined_path"] = quarantine;
                }
                else
                {
                    attempt["target_after_failure"] = "ABSENT";
                }

                if (!transient || attemptNumber == maxAttempts)
                {
                    return errorPrefix + "_ARCHIVE_FAILED";
                }
                int waitMs = backoffMs.Length == 0 ? 0 : backoffMs[Math.Min(attemptNumber - 1, backoffMs.Length - 1)];
                attempt["retry_wait_ms"] = waitMs;
                Checkpoint("archive_retry_wait", waitMs + "ms");
                sleep(waitMs);
            }
            return errorPrefix + "_ARCHIVE_FAILED";
        }

        private static string _checkpointPath;

        /// <summary>
        /// Checkpoint persistente ANTES/DESPUES de cada operacion Openness. Lo escribe este proceso (no TIA),
        /// en modo append + WriteThrough + Flush(true): cada linea queda en disco aunque TIA Portal se caiga
        /// o el bridge sea terminado despues. Formato: timestamp TAB checkpoint TAB detalle.
        /// </summary>
        private static void Checkpoint(string name, string detail)
        {
            if (String.IsNullOrWhiteSpace(_checkpointPath))
            {
                return;
            }
            try
            {
                string line = DateTime.Now.ToString("yyyy-MM-ddTHH:mm:ss.fff") + "\t" + name + "\t"
                    + (detail ?? "").Replace("\r", " ").Replace("\n", " ") + Environment.NewLine;
                byte[] bytes = System.Text.Encoding.UTF8.GetBytes(line);
                using (FileStream stream = new FileStream(_checkpointPath, FileMode.Append, FileAccess.Write, FileShare.ReadWrite, 4096, FileOptions.WriteThrough))
                {
                    stream.Write(bytes, 0, bytes.Length);
                    stream.Flush(true);
                }
            }
            catch (Exception)
            {
                // Un checkpoint nunca debe romper la evaluacion.
            }
        }

        private static int GetInt(Dictionary<string, object> payload, string key, int defaultValue)
        {
            object raw;
            int value;
            if (payload.TryGetValue(key, out raw) && raw != null && Int32.TryParse(raw.ToString(), out value))
            {
                return value;
            }
            return defaultValue;
        }

        /// <summary>
        /// Escribe archived.json (ruta + SHA-256 del .zap18 del workspace) y espera proceed.json de Python.
        /// Devuelve true solo si Python confirma {"download": true} (copia de evidencia verificada).
        /// </summary>
        private static bool WaitForProceed(string handshakeDir, Dictionary<string, object> report, int timeoutSeconds)
        {
            string archivedPath = Path.Combine(handshakeDir, "archived.json");
            string proceedPath = Path.Combine(handshakeDir, "proceed.json");
            WriteJson(archivedPath, new Dictionary<string, object>
            {
                { "archive_path", GetString(report, "archive_path", "") },
                { "archive_sha256", GetString(report, "archive_sha256", "") },
                { "written_at", DateTime.Now.ToString("s") }
            });
            Log("[TIA HANDSHAKE] archived.json escrito; esperando proceed.json");
            DateTime deadline = DateTime.Now.AddSeconds(timeoutSeconds);
            while (DateTime.Now < deadline)
            {
                if (File.Exists(proceedPath))
                {
                    try
                    {
                        Dictionary<string, object> decision = ReadJson(proceedPath);
                        bool download = GetBool(decision, "download", false);
                        report["handshake"] = new Dictionary<string, object>
                        {
                            { "download", download }, { "reason", GetString(decision, "reason", "") }
                        };
                        return download;
                    }
                    catch (Exception)
                    {
                        // proceed.json aun escribiendose: reintentar
                    }
                }
                System.Threading.Thread.Sleep(500);
            }
            report["handshake"] = new Dictionary<string, object> { { "download", false }, { "reason", "HANDSHAKE_TIMEOUT" } };
            return false;
        }

        /// <summary>
        /// Diagnostico: Projects.Retrieve de un .zap18 en un directorio, informa la ruta REAL del proyecto
        /// recuperado (si TIA crea o no subcarpeta) y el archivo con la ruta mas larga. Cierra sin guardar.
        /// Sirve para conocer el layout de Retrieve y validar el limite de ruta de TIA antes de evaluar.
        /// </summary>
        private static Dictionary<string, object> ExecuteRetrieveProbe(Dictionary<string, object> request)
        {
            Dictionary<string, object> report = NewReport("RUNNING");
            string archive = GetRequiredString(request, "archive_path");
            string target = GetRequiredString(request, "target_dir");
            report["archive_path"] = archive;
            report["target_dir"] = target;
            report["target_dir_length"] = target.Length;
            TiaPortal portal = null;
            Project project = null;
            try
            {
                if (Directory.Exists(target) && Directory.EnumerateFileSystemEntries(target).Any())
                {
                    throw new InvalidOperationException("target_dir is not empty");
                }
                Directory.CreateDirectory(target);
                portal = new TiaPortal(TiaPortalMode.WithoutUserInterface);
                project = portal.Projects.Retrieve(new FileInfo(archive), new DirectoryInfo(target));
                string projectPath = project.Path.FullName;
                report["retrieved_project_path"] = projectPath;
                report["retrieved_project_path_length"] = projectPath.Length;
                report["retrieved_project_dir"] = Path.GetDirectoryName(projectPath);
                report["subfolder_created"] = !PathsEqual(Path.GetDirectoryName(projectPath), target);
                string longest = Directory.GetFiles(target, "*", SearchOption.AllDirectories).OrderByDescending(f => f.Length).FirstOrDefault();
                report["longest_file"] = longest;
                report["longest_file_length"] = longest == null ? 0 : longest.Length;
                report["status"] = "TIA_RETRIEVE_PROBE_PASSED";
            }
            catch (Exception exception)
            {
                report["status"] = "TIA_RETRIEVE_PROBE_FAILED";
                report["exception_type"] = exception.GetType().FullName;
                AddError(report, exception.GetType().FullName + ": " + exception.Message);
            }
            finally
            {
                try
                {
                    if (project != null)
                    {
                        project.Close();
                    }
                }
                catch (Exception)
                {
                }
                if (portal != null)
                {
                    portal.Dispose();
                }
            }
            return report;
        }

        /// <summary>
        /// VALIDAR MASTER: abre el MASTER (o se adjunta si ya esta abierto), verifica V18, lo describe
        /// (CPU, interfaces/IP, bloques, tablas) y crea un SNAPSHOT .zap18 con Project.Archive. El MASTER
        /// nunca se guarda ni se modifica: con cambios sin guardar se detiene (MASTER_UNSAVED_CHANGES).
        /// Cada etapa tiene su propio codigo; la descripcion obtenida nunca se pierde por un fallo posterior.
        /// </summary>
        private static Dictionary<string, object> ExecuteValidateMaster(Dictionary<string, object> request)
        {
            Dictionary<string, object> report = NewReport("RUNNING");
            string masterPath = GetRequiredString(request, "master_project_path");
            string archiveDir = GetRequiredString(request, "archive_dir");
            string archiveName = GetRequiredString(request, "archive_name");
            string requestedPlcName = GetString(request, "plc_name", "");
            bool attach = GetBool(request, "attach_to_running", true);

            TiaPortal portal = null;
            Project project = null;
            bool attachedToExisting = false;
            try
            {
                try
                {
                    if (!masterPath.EndsWith(".ap18", StringComparison.OrdinalIgnoreCase))
                    {
                        throw new InvalidOperationException("El MASTER no es un proyecto TIA Portal V18 (.ap18): " + masterPath);
                    }
                    if (attach)
                    {
                        foreach (TiaPortalProcess process in TiaPortal.GetProcesses())
                        {
                            if (process.ProjectPath != null && PathsEqual(process.ProjectPath.FullName, masterPath))
                            {
                                portal = process.Attach();
                                project = portal.Projects.FirstOrDefault(p => PathsEqual(p.Path.FullName, masterPath));
                                attachedToExisting = project != null;
                                break;
                            }
                        }
                    }
                    if (project == null)
                    {
                        if (portal != null)
                        {
                            portal.Dispose();
                        }
                        portal = new TiaPortal(TiaPortalMode.WithoutUserInterface);
                        project = portal.Projects.Open(new FileInfo(masterPath));
                    }
                }
                catch (Exception exception)
                {
                    report["status"] = "MASTER_OPEN_FAILED";
                    report["exception_type"] = exception.GetType().FullName;
                    AddError(report, exception.GetType().FullName + ": " + exception.Message);
                    return report;
                }
                report["attached_to_existing_tia"] = attachedToExisting;
                report["master_project_path"] = project.Path.FullName;
                report["master_is_modified"] = project.IsModified;
                report["master_project_version"] = project.Version;
                try
                {
                    report["master"] = DescribePlcProject(project, requestedPlcName);
                }
                catch (Exception exception)
                {
                    List<string> warnings = report["warnings"] as List<string>;
                    if (warnings != null)
                    {
                        warnings.Add("MASTER_DESCRIBE_FAILED: " + exception.GetType().FullName + ": " + exception.Message);
                    }
                }

                // Guardar "si corresponde": un MASTER abierto por el bridge no tiene cambios; con cambios
                // sin guardar (MASTER abierto en otra sesion TIA) NO se guarda (seria modificar el MASTER).
                if (project.IsModified)
                {
                    report["status"] = "MASTER_UNSAVED_CHANGES";
                    AddError(report, "El MASTER tiene cambios sin guardar en TIA Portal. Guardelo o cierrelo y vuelva a validar (el MASTER nunca se guarda desde la aplicacion).");
                    return report;
                }

                string archiveStatus = ArchiveProject(project, archiveDir, archiveName, report, "MASTER");
                if (archiveStatus != "CREATED")
                {
                    report["status"] = archiveStatus;
                    AddError(report, archiveStatus + ": " + GetString(report, "archive_error", ""));
                    return report;
                }
                report["status"] = "TIA_MASTER_VALIDATION_PASSED";
            }
            finally
            {
                try
                {
                    if (!attachedToExisting && project != null)
                    {
                        project.Close();
                    }
                }
                catch (Exception)
                {
                }
                if (portal != null)
                {
                    portal.Dispose();
                }
            }
            return report;
        }

        /// <summary>
        /// EVALUAR ENSAYO GUARDADO: en una sesion TIA PROPIA (nunca se adjunta a otra), recupera una
        /// copia nueva del snapshot MASTER dentro del ensayo, reconcilia PLC_Agent_IO, elimina solo
        /// bloques APP_MANAGED que la fuente actual no redefine, importa EXACTAMENTE program.scl,
        /// compila, guarda, archiva el proyecto del ensayo (.zap18) y, solo si compilo y el archivo
        /// existe, descarga a PLCSIM (mismas guardias que la accion download).
        /// </summary>
        private static Dictionary<string, object> ExecuteEvaluateTrial(Dictionary<string, object> request)
        {
            Dictionary<string, object> report = NewReport("RUNNING");
            string masterArchive = GetRequiredString(request, "master_archive_path");
            string workingDir = GetRequiredString(request, "working_dir");
            string trialArchiveDir = GetRequiredString(request, "trial_archive_dir");
            string trialArchiveName = GetRequiredString(request, "trial_archive_name");
            string sourcePath = GetRequiredString(request, "source_path");
            string sourceName = GetString(request, "source_name", Path.GetFileName(sourcePath));
            string requestedPlcName = GetString(request, "plc_name", "");
            bool withUi = GetBool(request, "with_user_interface", false);
            bool downloadAfterArchive = GetBool(request, "download_after_archive", false);
            List<string> deleteBlocks = GetStringList(request, "delete_blocks");
            List<Dictionary<string, object>> stages = new List<Dictionary<string, object>>();
            report["stages"] = stages;
            report["archive_status"] = "NOT_CREATED";
            report["physical_download_executed"] = false;

            _checkpointPath = GetString(request, "checkpoint_path", "");
            report["checkpoint_path"] = _checkpointPath;
            string stage = "start_tia";
            TiaPortal portal = null;
            Project project = null;
            Dictionary<string,object> nativeRequest=null,nativeManifest=null,nativeLoop=null;
            if(request.ContainsKey("native_pid"))
            {
                PidControlSupport.VerifyExperimentalTarget(GetString(request,"target_type",""),
                    GetString(request,"purpose",""),GetBool(request,"require_simulation",false),
                    GetBool(request,"physical_download_allowed",true));
                var native=request["native_pid"] as Dictionary<string,object>;
                if(native==null)throw new InvalidOperationException("PID_BUNDLE_INTEGRITY: malformed native request");
                nativeRequest=new Dictionary<string,object>(request);
                foreach(var item in native)nativeRequest[item.Key]=item.Value;
                string boundary=Path.GetFullPath(GetRequiredString(request,"handshake_dir")).TrimEnd(Path.DirectorySeparatorChar)+Path.DirectorySeparatorChar;
                foreach(string key in new[]{"source_path","pid_manifest_path","pid_bindings_path","pid_cyclic_ob_path"})
                    if(!Path.GetFullPath(GetRequiredString(nativeRequest,key)).StartsWith(boundary,StringComparison.OrdinalIgnoreCase))
                        throw new InvalidOperationException("PID_BUNDLE_INTEGRITY: native file outside workspace");
                PidControlSupport.VerifyFileHash(sourcePath,GetRequiredString(nativeRequest,"pid_source_sha256"));
                PidControlSupport.VerifyFileHash(GetRequiredString(nativeRequest,"pid_cyclic_ob_path"),GetRequiredString(nativeRequest,"pid_cyclic_ob_sha256"));
                PidControlSupport.VerifyFileHash(GetRequiredString(nativeRequest,"pid_manifest_path"),GetRequiredString(nativeRequest,"pid_manifest_sha256"));
                PidControlSupport.VerifyFileHash(GetRequiredString(nativeRequest,"pid_bindings_path"),GetRequiredString(nativeRequest,"pid_bindings_sha256"));
                nativeManifest=ReadJson(GetRequiredString(nativeRequest,"pid_manifest_path"));
                nativeLoop=PidControlSupport.ValidateManifest(nativeManifest);
                report["pid_project_mode"]="EXPERIMENT_COPY";
                report["configuration_hash"]=nativeLoop["configuration_hash"];
                foreach(string key in new[]{"pid_source_sha256","pid_cyclic_ob_sha256","pid_manifest_sha256","pid_bindings_sha256"})
                    report[key]=nativeRequest[key];
            }
            try
            {
                try
                {
                    Checkpoint("tia_start_started", withUi ? "WithUserInterface" : "WithoutUserInterface");
                    portal = new TiaPortal(withUi ? TiaPortalMode.WithUserInterface : TiaPortalMode.WithoutUserInterface);
                    Checkpoint("tia_start_completed", "");
                    stages.Add(new Dictionary<string, object> { { "stage", stage }, { "ok", true } });

                    stage = "retrieve_master_copy";
                    if (Directory.Exists(workingDir) && Directory.EnumerateFileSystemEntries(workingDir).Any())
                    {
                        throw new InvalidOperationException("working_dir is not empty: a trial copy is never reused.");
                    }
                    Directory.CreateDirectory(workingDir);
                    Checkpoint("retrieve_started", masterArchive + " -> " + workingDir);
                    project = portal.Projects.Retrieve(new FileInfo(masterArchive), new DirectoryInfo(workingDir));
                    string projectPath = project.Path.FullName;
                    Checkpoint("retrieve_completed", projectPath + " (" + projectPath.Length + " chars)");
                    if (!projectPath.StartsWith(Path.GetFullPath(workingDir), StringComparison.OrdinalIgnoreCase))
                    {
                        throw new InvalidOperationException("Retrieved project is outside the trial working_dir: " + projectPath);
                    }
                    report["working_project_path"] = projectPath;
                    stages.Add(new Dictionary<string, object> { { "stage", stage }, { "ok", true } });

                    // Verificacion MINIMA de identidad de la copia (Fase 4A-TIA-STABILITY): nombre del proyecto
                    // y software PLC accesible. NO se describen interfaces/nodos/bloques: CPU, X1, IP, etc. ya
                    // los registro VALIDAR MASTER (metadata congelada). La descripcion completa provoco el OOM de T0001.
                    stage = "minimal_identity";
                    Checkpoint("minimal_identity_started", "");
                    string expectedProjectName = GetString(request, "expected_project_name", "");
                    string projectName = project.Name;
                    if (!String.IsNullOrWhiteSpace(expectedProjectName)
                        && !String.Equals(projectName, expectedProjectName, StringComparison.OrdinalIgnoreCase))
                    {
                        throw new InvalidOperationException("Retrieved project '" + projectName + "' is not the MASTER '" + expectedProjectName + "'.");
                    }
                    PlcSoftware plcSoftware = FindPlcSoftware(project, requestedPlcName);
                    if (plcSoftware == null)
                    {
                        throw new InvalidOperationException("No PLC software was found in the trial project copy.");
                    }
                    report["plc_name"] = plcSoftware.Name;
                    report["copy_identity"] = new Dictionary<string, object>
                    {
                        { "project_name", projectName }, { "expected_project_name", expectedProjectName }, { "plc_name", plcSoftware.Name }
                    };
                    Checkpoint("minimal_identity_completed", projectName + " / " + plcSoftware.Name);
                    stages.Add(new Dictionary<string, object> { { "stage", stage }, { "ok", true } });

                    stage = "sync_tags";
                    Checkpoint("tags_started", "PLC_Agent_IO");
                    report["tag_reconciliation"] = EnsureTags(plcSoftware, request);
                    Checkpoint("tags_completed", "");
                    stages.Add(new Dictionary<string, object> { { "stage", stage }, { "ok", true } });

                    stage = "remove_managed_blocks";
                    Checkpoint("managed_blocks_started", String.Join(",", deleteBlocks));
                    List<string> removed = new List<string>();
                    foreach (string name in deleteBlocks)
                    {
                        PlcBlock block = FindBlock(plcSoftware.BlockGroup, name);
                        if (block != null)
                        {
                            block.Delete();
                            removed.Add(name);
                        }
                    }
                    report["removed_managed_blocks"] = removed;
                    Checkpoint("managed_blocks_completed", String.Join(",", removed));
                    stages.Add(new Dictionary<string, object> { { "stage", stage }, { "ok", true } });

                    stage = "generate_blocks";
                    Checkpoint("import_started", sourcePath);
                    PlcExternalSource existing = plcSoftware.ExternalSourceGroup.ExternalSources.Find(sourceName);
                    if (existing != null)
                    {
                        existing.Delete();
                    }
                    PlcExternalSource source = plcSoftware.ExternalSourceGroup.ExternalSources.CreateFromFile(sourceName, sourcePath);
                    report["imported_source_sha256"] = Sha256File(sourcePath);
                    if(nativeManifest!=null)
                    {
                        string nativeStage=Path.Combine(workingDir,"np");Directory.CreateDirectory(nativeStage);
                        plcSoftware=GenerateNativePidBlocks(project,nativeRequest,nativeManifest,nativeLoop,report,nativeStage,false);
                        report["generated_blocks_count"]=3;
                        report["project_path"]=project.Path.FullName;
                    }
                    else
                    {
                        IList<IEngineeringObject> generatedBlocks = source.GenerateBlocksFromSource(GenerateBlockOption.None);
                        report["generated_blocks_count"] = generatedBlocks == null ? 0 : generatedBlocks.Count;
                    }
                    Checkpoint("import_completed", "blocks=" + report["generated_blocks_count"]);
                    stages.Add(new Dictionary<string, object> { { "stage", stage }, { "ok", true } });

                    stage = "compile";
                    Checkpoint("compile_started", "");
                    ICompilable compilable = plcSoftware.GetService<ICompilable>();
                    if (compilable == null)
                    {
                        throw new InvalidOperationException("The PLC software does not expose the compile service.");
                    }
                    CompilerResult compileResult = compilable.Compile();
                    report["error_count"] = compileResult.ErrorCount;
                    report["warning_count"] = compileResult.WarningCount;
                    report["compiler_state"] = compileResult.State.ToString();
                    report["compiler_messages"] = FlattenMessages(compileResult.Messages);
                    if(nativeManifest!=null && compileResult.ErrorCount==0)
                    {
                        report["pid_cyclic_ob"]=PidControlSupport.VerifyCyclic(plcSoftware,nativeManifest,false);
                        report["pid_infrastructure_after"]=PidControlSupport.Ensure(plcSoftware,nativeManifest);
                        report["cpu"]=DescribeCpuIdentity(project,requestedPlcName);
                    }
                    report["status"] = compileResult.ErrorCount == 0 ? "TIA_COMPILATION_PASSED" : "TIA_COMPILATION_FAILED";
                    Checkpoint("compile_completed", "errors=" + compileResult.ErrorCount + " warnings=" + compileResult.WarningCount);
                    // Solo NOMBRES de bloques (sin atributos enumerados ni interfaces) para detectar logica no administrada.
                    stage = "list_blocks";
                    Checkpoint("list_blocks_started", "");
                    report["blocks_after_compile"] = ListBlockNames(plcSoftware.BlockGroup, "");
                    Checkpoint("list_blocks_completed", "");
                    stages.Add(new Dictionary<string, object> { { "stage", stage }, { "ok", compileResult.ErrorCount == 0 } });
                }
                catch (Exception exception)
                {
                    report["status"] = exception is TagSynchronizationException ? "TIA_TAG_SYNC_ERROR" : "TIA_OPENNESS_ERROR";
                    report["failed_stage"] = stage;
                    report["exception_type"] = exception.GetType().FullName;
                    report["exception"] = exception.ToString();
                    AddError(report, exception.GetType().FullName + ": " + exception.Message);
                    stages.Add(new Dictionary<string, object> { { "stage", stage }, { "ok", false } });
                    Checkpoint(stage + "_failed", exception.GetType().FullName + ": " + exception.Message);
                }

                // Guardar + archivar SIEMPRE que haya proyecto (tambien con fallo de compilacion).
                if (project != null)
                {
                    try
                    {
                        Checkpoint("save_started", "");
                        project.Save();
                        Checkpoint("save_completed", "");
                        report["project_saved"] = true;
                        // Espera fija y determinista tras Save: deja terminar al indexador de busqueda de TIA
                        // (IM/SearchIndex) antes de que Archive copie el proyecto.
                        Checkpoint("archive_settle_wait", TrialArchiveSettleMs + "ms");
                        System.Threading.Thread.Sleep(TrialArchiveSettleMs);
                        report["archive_settle_ms"] = TrialArchiveSettleMs;
                        Checkpoint("archive_started", Path.Combine(trialArchiveDir, trialArchiveName));
                        string archiveStatus = ArchiveProject(project, trialArchiveDir, trialArchiveName, report, "TRIAL", TrialArchiveMaxAttempts);
                        Checkpoint(archiveStatus == "CREATED" ? "archive_completed" : "archive_failed", archiveStatus);
                        report["archive_status"] = archiveStatus == "CREATED" ? "CREATED" : "NOT_CREATED";
                        report["archive_result"] = archiveStatus;
                        stages.Add(new Dictionary<string, object> { { "stage", "archive" }, { "ok", archiveStatus == "CREATED" } });
                    }
                    catch (Exception exception)
                    {
                        report["archive_status"] = "NOT_CREATED";
                        report["archive_error_type"] = exception.GetType().FullName;
                        report["archive_error"] = exception.Message;
                        Checkpoint("save_or_archive_failed", exception.GetType().FullName + ": " + exception.Message);
                        stages.Add(new Dictionary<string, object> { { "stage", "archive" }, { "ok", false } });
                    }
                }

                bool compiled = GetString(report, "status", "") == "TIA_COMPILATION_PASSED";
                bool proceedToDownload = downloadAfterArchive && compiled && GetString(report, "archive_status", "") == "CREATED";
                string handshakeDir = GetString(request, "handshake_dir", "");
                if (proceedToDownload && !String.IsNullOrWhiteSpace(handshakeDir))
                {
                    // Handshake: Python copia y verifica el .zap18 en la evidencia del ensayo ANTES de descargar
                    // (misma sesion TIA: sin segundo Retrieve). Sin confirmacion no se descarga.
                    Checkpoint("handshake_started", "");
                    proceedToDownload = WaitForProceed(handshakeDir, report, GetInt(request, "handshake_timeout_seconds", 600));
                    Checkpoint("handshake_completed", "download=" + proceedToDownload);
                }
                if (proceedToDownload)
                {
                    Dictionary<string, object> download = NewReport("RUNNING");
                    try
                    {
                        Checkpoint("download_started", "PLCSIM_ADVANCED");
                        RunDownload(project, request, download);
                        Checkpoint("download_completed", GetString(download, "status", ""));
                    }
                    catch (Exception exception)
                    {
                        Checkpoint("download_failed", exception.GetType().FullName + ": " + exception.Message);
                        download["status"] = "TIA_DOWNLOAD_FAILED";
                        download["exception_type"] = exception.GetType().FullName;
                        download["exception"] = exception.ToString();
                        AddError(download, exception.GetType().FullName + ": " + exception.Message);
                    }
                    report["download"] = download;
                    stages.Add(new Dictionary<string, object> { { "stage", "download" }, { "ok", GetString(download, "status", "") == "TIA_DOWNLOAD_PASSED" } });
                }
            }
            finally
            {
                try
                {
                    if (project != null)
                    {
                        project.Close();
                    }
                }
                catch (Exception)
                {
                }
                if (portal != null)
                {
                    portal.Dispose();
                }
            }
            return report;
        }

        private static Dictionary<string, object> NewReport(string status)
        {
            return new Dictionary<string, object>
            {
                { "status", status },
                { "timestamp", DateTime.Now.ToString("s") },
                { "tia_version", "V18" },
                { "errors", new List<string>() },
                { "warnings", new List<string>() }
            };
        }

        private static void AddError(Dictionary<string, object> report, string error)
        {
            List<string> errors = report["errors"] as List<string>;
            if (errors != null)
            {
                errors.Add(error);
            }
        }

        /// <summary>
        /// Errores especificos de la etapa de reconciliacion de PLC tags (EnsureTags), distintos
        /// de un InvalidOperationException generico de otra etapa - permite a Main() asignar el
        /// status "TIA_TAG_SYNC_ERROR" en vez de "TIA_OPENNESS_ERROR" (seccion 17).
        /// </summary>
        private sealed class TagSynchronizationException : InvalidOperationException
        {
            public TagSynchronizationException(string message) : base(message)
            {
            }
        }

        /// <summary>
        /// Progreso de reconciliacion de tags (seccion 16, formato "[TIA TAGS] ..."). Va a stderr,
        /// nunca a stdout - stdout esta reservado para la unica linea final Json.Serialize(report)
        /// que Main() escribe (linea ~79), y Python la captura por separado en bridge_stdout/
        /// bridge_stderr para diagnostico sin necesidad de parsearla como JSON.
        /// </summary>
        private static void Log(string message)
        {
            Console.Error.WriteLine(message);
        }

        private static Dictionary<string, object> ReadJson(string path)
        {
            return Json.Deserialize<Dictionary<string, object>>(File.ReadAllText(path));
        }

        private static void WriteJson(string path, Dictionary<string, object> payload)
        {
            string directory = Path.GetDirectoryName(path);
            if (!String.IsNullOrWhiteSpace(directory))
            {
                Directory.CreateDirectory(directory);
            }
            File.WriteAllText(path, Json.Serialize(payload));
        }

        private static string GetRequiredString(Dictionary<string, object> payload, string key)
        {
            string value = GetString(payload, key, "");
            if (String.IsNullOrWhiteSpace(value))
            {
                throw new ArgumentException("Missing required request field: " + key);
            }
            return value;
        }

        private static string GetString(Dictionary<string, object> payload, string key, string defaultValue)
        {
            object value;
            return payload.TryGetValue(key, out value) && value != null ? Convert.ToString(value) : defaultValue;
        }

        private static bool GetBool(Dictionary<string, object> payload, string key, bool defaultValue)
        {
            object value;
            if (!payload.TryGetValue(key, out value) || value == null)
            {
                return defaultValue;
            }
            return Convert.ToBoolean(value);
        }

        private static bool PathsEqual(string firstPath, string secondPath)
        {
            return String.Equals(
                Path.GetFullPath(firstPath).TrimEnd(Path.DirectorySeparatorChar),
                Path.GetFullPath(secondPath).TrimEnd(Path.DirectorySeparatorChar),
                StringComparison.OrdinalIgnoreCase
            );
        }

        // Seccion 7: %IX16.0 (convencion IEC/de la aplicacion, ver mapa_banco_fisico.json) y
        // %I16.0 (formato que TIA/Siemens reporta via PlcTag.LogicalAddress) representan la MISMA
        // direccion fisica BOOL - la "X" es un calificador de tamano opcional, no parte de la
        // direccion. Solo se reconoce para I/Q/M booleanos (unico tipo que esta aplicacion genera
        // para I_/Q_ - variables.json siempre usa data_type "Bool"); cualquier otro formato
        // (%IW.../%QD... o algo irreconocible) se compara tal cual, sin canonicalizar.
        private static readonly Regex BoolAddressPattern = new Regex(
            @"^%(?<area>[IQM])X?(?<byte>\d+)\.(?<bit>\d+)$",
            RegexOptions.IgnoreCase | RegexOptions.Compiled
        );

        private static string NormalizeAddress(string address)
        {
            string trimmed = (address ?? "").Replace(" ", "").Trim().ToUpperInvariant();
            Match match = BoolAddressPattern.Match(trimmed);
            if (!match.Success)
            {
                return trimmed;
            }
            return "%" + match.Groups["area"].Value + match.Groups["byte"].Value + "." + match.Groups["bit"].Value;
        }

        private static Assembly ResolveSiemensAssembly(object sender, ResolveEventArgs args)
        {
            string assemblyName = new AssemblyName(args.Name).Name + ".dll";
            string[] searchDirectories =
            {
                Path.Combine(PortalRoot, "PublicAPI", "V18"),
                Path.Combine(PortalRoot, "Bin", "PublicAPI"),
                Path.Combine(PortalRoot, "Bin")
            };
            foreach (string directory in searchDirectories)
            {
                string candidate = Path.Combine(directory, assemblyName);
                if (File.Exists(candidate))
                {
                    return Assembly.LoadFrom(candidate);
                }
            }
            return null;
        }
    }
}
