using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Web.Script.Serialization;

using Siemens.Engineering;
using Siemens.Engineering.Compiler;
using Siemens.Engineering.Connection;
using Siemens.Engineering.Download;
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
                else
                {
                    report = NewReport("TIA_OPENNESS_ERROR");
                    AddError(report, "Unknown action: " + action);
                }
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
                    report["tags"] = EnsureTags(plcSoftware, request);
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

        private static Dictionary<string, object> EnsureTags(PlcSoftware plcSoftware, Dictionary<string, object> request)
        {
            PlcTagTable table = plcSoftware.TagTableGroup.TagTables.Find("PLC_Agent_IO");
            if (table == null)
            {
                table = plcSoftware.TagTableGroup.TagTables.Create("PLC_Agent_IO");
            }
            int created = 0;
            int existing = 0;
            int requested = 0;
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

            foreach (object rawTag in tagItems)
            {
                Dictionary<string, object> tag = rawTag as Dictionary<string, object>;
                if (tag == null)
                {
                    throw new InvalidOperationException("The TIA request contains an invalid tag entry.");
                }
                requested++;
                string name = GetRequiredString(tag, "name");
                string dataType = GetString(tag, "data_type", "Bool");
                string address = GetRequiredString(tag, "address");
                PlcTag existingTag = table.Tags.Find(name);
                if (existingTag == null)
                {
                    table.Tags.Create(name, dataType, address);
                    created++;
                }
                else
                {
                    bool sameType = String.Equals(
                        existingTag.DataTypeName,
                        dataType,
                        StringComparison.OrdinalIgnoreCase
                    );
                    bool sameAddress = String.Equals(
                        NormalizeAddress(existingTag.LogicalAddress),
                        NormalizeAddress(address),
                        StringComparison.OrdinalIgnoreCase
                    );
                    if (!sameType || !sameAddress)
                    {
                        throw new InvalidOperationException(
                            "Authorized tag conflict for " + name
                            + ". Existing: " + existingTag.DataTypeName + " " + existingTag.LogicalAddress
                            + "; requested: " + dataType + " " + address
                        );
                    }
                    existing++;
                }
            }
            if (requested == 0)
            {
                throw new InvalidOperationException("No authorized PLC tags were received; block generation was stopped.");
            }
            return new Dictionary<string, object>
            {
                { "table", table.Name },
                { "requested", requested },
                { "created", created },
                { "existing", existing }
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

                IConfiguration targetConfiguration = ResolveUnambiguousTargetInterface(downloadProvider.Configuration, report);
                if (targetConfiguration == null)
                {
                    report["status"] = "TIA_DOWNLOAD_AMBIGUOUS_TARGET";
                    return report;
                }

                // Software-only download: never touches hardware configuration, IP addresses,
                // racks or modules. preDownloadConfigurationDelegate/postDownloadConfigurationDelegate
                // are intentionally null - this reuses whatever online/download connection is
                // already configured and saved in the project instead of auto-selecting one.
                DownloadResult downloadResult = downloadProvider.Download(
                    targetConfiguration,
                    null,
                    null,
                    DownloadOptions.Software
                );

                int errorCount = downloadResult.ErrorCount;
                int warningCount = downloadResult.WarningCount;
                bool success = errorCount == 0 && downloadResult.State != DownloadResultState.Error;

                report["download_state"] = downloadResult.State.ToString();
                report["download_error_count"] = errorCount;
                report["download_warning_count"] = warningCount;
                report["download_messages"] = FlattenDownloadMessages(downloadResult.Messages);
                report["success"] = success;
                report["status"] = success ? "TIA_DOWNLOAD_PASSED" : "TIA_DOWNLOAD_FAILED";
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

        /// <summary>
        /// Walks Modes -> PcInterfaces -> TargetInterfaces and only returns a target when each
        /// level has exactly one candidate. Never scans the network or picks arbitrarily among
        /// several - if more than one option exists anywhere, the caller must abort.
        /// </summary>
        private static IConfiguration ResolveUnambiguousTargetInterface(ConnectionConfiguration connectionConfiguration, Dictionary<string, object> report)
        {
            List<ConfigurationMode> modes = connectionConfiguration.Modes.ToList();
            if (modes.Count != 1)
            {
                report["available_modes"] = modes.Select(m => m.Name).ToList();
                AddError(report, "No se pudo determinar de forma inequivoca el modo de conexion (PN/IE, MPI, etc.) del PLC objetivo.");
                return null;
            }

            List<ConfigurationPcInterface> pcInterfaces = modes[0].PcInterfaces.ToList();
            if (pcInterfaces.Count != 1)
            {
                report["available_pc_interfaces"] = pcInterfaces.Select(i => i.Name).ToList();
                AddError(report, "No se pudo determinar de forma inequivoca la interfaz PC/PG para descargar al PLC.");
                return null;
            }

            List<ConfigurationTargetInterface> targetInterfaces = pcInterfaces[0].TargetInterfaces.ToList();
            if (targetInterfaces.Count != 1)
            {
                report["available_target_interfaces"] = targetInterfaces.Select(i => i.Name).ToList();
                AddError(report, "No se pudo determinar de forma inequivoca el dispositivo objetivo accesible para el PLC.");
                return null;
            }

            report["target_interface_name"] = targetInterfaces[0].Name;
            return targetInterfaces[0];
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

        private static string NormalizeAddress(string address)
        {
            return (address ?? "").Replace(" ", "").Trim().ToUpperInvariant();
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
