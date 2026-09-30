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
                report["success"] = GetString(report, "status", "").EndsWith("PASSED", StringComparison.Ordinal);
            }

            WriteJson(resultPath, report);
            Console.WriteLine(Json.Serialize(report));
            return GetString(report, "status", "").EndsWith("PASSED", StringComparison.Ordinal) ? 0 : 1;
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

                string openProjectPath = project.Path.FullName;
                if (!String.IsNullOrWhiteSpace(projectPath) && !PathsEqual(projectPath, openProjectPath))
                {
                    throw new InvalidOperationException(
                        "The open TIA project does not match the configured project. Open: "
                        + openProjectPath + "; configured: " + projectPath
                    );
                }

                PlcSoftware plcSoftware = FindPlcSoftware(project, requestedPlcName);
                if (plcSoftware == null)
                {
                    throw new InvalidOperationException("No PLC software was found in the TIA Portal project.");
                }

                report["attached_to_existing_tia"] = attachedToExisting;
                report["project_path"] = openProjectPath;
                report["plc_name"] = plcSoftware.Name;
                report["source_path"] = sourcePath;
                report["physical_download_executed"] = false;

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
                    project.Save();
                    report["project_saved"] = true;
                }
                else
                {
                    report["project_saved"] = false;
                }
                report["status"] = success ? "TIA_COMPILATION_PASSED" : "TIA_COMPILATION_FAILED";
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

                report["attached_to_existing_tia"] = attachedToExisting;
                report["project_path"] = project.Path.FullName;
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
                    return report;
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
                    return report;
                }

                ConfigurationPcInterface pcInterface;
                IConfiguration targetConfiguration = ResolveDownloadTarget(downloadProvider.Configuration, request, targetType, report, out pcInterface);
                if (targetConfiguration == null)
                {
                    report["status"] = "TIA_DOWNLOAD_AMBIGUOUS_TARGET";
                    return report;
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
                    return report;
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
                    downloadResult = downloadProvider.Download(targetConfiguration, handler, handler, options);
                }
                catch (DownloadConfigurationRejectedException rejected)
                {
                    report["status"] = "DOWNLOAD_CONFIGURATION_UNSUPPORTED";
                    AddError(report, rejected.Message);
                    return report;
                }
                catch (Exception exception)
                {
                    // Openness puede envolver la excepcion lanzada dentro del delegado.
                    DownloadConfigurationRejectedException inner = FindInner<DownloadConfigurationRejectedException>(exception);
                    if (inner != null)
                    {
                        report["status"] = "DOWNLOAD_CONFIGURATION_UNSUPPORTED";
                        AddError(report, inner.Message);
                        return report;
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
        private static IConfiguration ResolveDownloadTarget(
            ConnectionConfiguration connectionConfiguration,
            Dictionary<string, object> request,
            string targetType,
            Dictionary<string, object> report,
            out ConfigurationPcInterface pcInterface)
        {
            pcInterface = null;
            string modeName = GetString(request, "configuration_mode", "").Trim();
            string pcName = GetString(request, "pc_interface", "").Trim();
            string targetName = GetString(request, "target_interface", "").Trim();

            List<object> available = new List<object>();
            List<KeyValuePair<ConfigurationMode, ConfigurationPcInterface>> candidates = new List<KeyValuePair<ConfigurationMode, ConfigurationPcInterface>>();
            foreach (ConfigurationMode mode in connectionConfiguration.Modes)
            {
                foreach (ConfigurationPcInterface candidate in mode.PcInterfaces)
                {
                    available.Add(new Dictionary<string, object>
                    {
                        { "mode", mode.Name },
                        { "pc_interface", candidate.Name },
                        { "number", candidate.Number },
                        { "target_interfaces", candidate.TargetInterfaces.Select(t => t.Name).ToList() }
                    });
                    if (modeName.Length > 0 && !String.Equals(mode.Name, modeName, StringComparison.OrdinalIgnoreCase))
                    {
                        continue;
                    }
                    bool match = pcName.Length > 0
                        ? String.Equals(candidate.Name, pcName, StringComparison.OrdinalIgnoreCase)
                        : targetType != TargetTypePlcsimAdvanced || candidate.Name.IndexOf("PLCSIM", StringComparison.OrdinalIgnoreCase) >= 0;
                    if (match)
                    {
                        candidates.Add(new KeyValuePair<ConfigurationMode, ConfigurationPcInterface>(mode, candidate));
                    }
                }
            }
            report["available_connections"] = available;

            if (candidates.Count != 1)
            {
                AddError(
                    report,
                    "No se pudo determinar de forma inequivoca la interfaz PG/PC de descarga (" + candidates.Count
                    + " candidatas). Configure 'pc_interface' en download_targets (ver available_connections)."
                );
                return null;
            }

            pcInterface = candidates[0].Value;
            report["configuration_mode"] = candidates[0].Key.Name;
            report["pc_interface_name"] = pcInterface.Name;

            List<ConfigurationTargetInterface> targets = pcInterface.TargetInterfaces.ToList();
            ConfigurationTargetInterface target = null;
            if (targetName.Length > 0)
            {
                target = targets.FirstOrDefault(t => String.Equals(t.Name, targetName, StringComparison.OrdinalIgnoreCase));
            }
            else if (targets.Count == 1)
            {
                target = targets[0];
            }
            if (target == null)
            {
                report["available_target_interfaces"] = targets.Select(t => t.Name).ToList();
                AddError(report, "No se pudo determinar de forma inequivoca la interfaz destino del PLC. Configure 'target_interface'.");
                return null;
            }
            report["target_interface_name"] = target.Name;
            return target;
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
