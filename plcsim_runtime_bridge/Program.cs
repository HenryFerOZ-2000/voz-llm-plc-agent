using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Net.NetworkInformation;
using System.Net.Sockets;
using System.Reflection;
using System.Runtime.CompilerServices;
using System.Threading;
using System.Web.Script.Serialization;

using Siemens.Simatic.Simulation.Runtime;

namespace VozLlmPlcAgent.PlcsimRuntimeBridge
{
    /// <summary>
    /// Puente de SOLO LECTURA hacia S7-PLCSIM Advanced V5 (Runtime API 5.0, x64). Fase 2A.
    ///
    /// Acciones:
    ///   - status          : Runtime Manager + instancias registradas + seleccion de la instancia
    ///                       pedida + adaptador de Windows. No abre la instancia.
    ///   - runtime_status  : lo anterior + CreateInterface(instancia unica) y lectura de
    ///                       OperatingState, CPUType, nombre del controlador e IPs.
    ///   - self_test       : logica pura (seleccion de instancia/adaptador, senales, variables
    ///                       internas, resolucion de nombres Runtime), sin PLCSIM.
    ///   - discover_tags   : (solo lectura) tags de DB del programa cargado con su nombre Runtime real.
    ///   - read_signal / write_input / io_sequence / restore_inputs : ver RuntimeIO (Fase 2B/3A y
    ///                       variables internas P01-P12).
    ///
    /// Nunca se invoca: RegisterInstance, PowerOn/PowerOff, Run/Stop, MemoryReset, SetIPSuite,
    /// SetNetInterfaceMapping, NetworkMode (set). Las unicas escrituras son las de RuntimeIO
    /// (InputArea.WriteBit y WriteBool/WriteFloat de variables internas escribibles); el resto son
    /// getters + Shutdown() (que segun SimulationRuntimeApi.h solo "termina la comunicacion con el
    /// Runtime Manager").
    ///
    /// Este bridge solo reporta HECHOS; los codigos de decision (red, cpu_run_confirmed, ...)
    /// se calculan en src/plcsim_runtime.py.
    /// </summary>
    internal static class Program
    {
        internal static readonly JavaScriptSerializer Json = new JavaScriptSerializer();
        internal const string DefaultApiDll =
            @"C:\Program Files (x86)\Common Files\Siemens\PLCSIMADV\API\5.0\Siemens.Simatic.Simulation.Runtime.Api.x64.dll";
        private static string apiDllPath = DefaultApiDll;

        private static int Main(string[] args)
        {
            if (args.Length != 1 || !File.Exists(args[0]))
            {
                Console.Error.WriteLine("Usage: PlcsimRuntimeBridge.exe <request.json>");
                return 2;
            }

            Dictionary<string, object> request = Json.Deserialize<Dictionary<string, object>>(File.ReadAllText(args[0]));
            string resultPath = GetString(request, "result_path", Path.Combine(Path.GetDirectoryName(args[0]), "plcsim_runtime_raw.json"));
            apiDllPath = GetString(request, "api_dll_path", DefaultApiDll);
            // La API se carga desde su ruta instalada (nunca se copia junto al exe): la DLL
            // manejada debe coincidir con el Runtime Manager instalado.
            AppDomain.CurrentDomain.AssemblyResolve += ResolveRuntimeApi;

            string action = GetString(request, "action", "status");
            Dictionary<string, object> report;
            try
            {
                if (action == "self_test")
                {
                    report = RunSelfTest();
                }
                else if (action == "status" || action == "runtime_status")
                {
                    report = RuntimeReader.Execute(request, action == "runtime_status", apiDllPath);
                }
                else if (action == "read_signal" || action == "write_input" || action == "io_sequence" || action == "restore_inputs"
                    || action == "discover_tags")
                {
                    report = RuntimeIO.Execute(request, action);
                }
                else
                {
                    report = NewReport("PLCSIM_RUNTIME_ERROR", action);
                    AddError(report, "Unknown action: " + action);
                }
            }
            catch (Exception exception)
            {
                bool apiMissing = exception is FileNotFoundException
                    || exception is FileLoadException
                    || exception is BadImageFormatException;
                report = NewReport(apiMissing ? "PLCSIM_API_NOT_AVAILABLE" : "PLCSIM_RUNTIME_ERROR", action);
                AddError(report, exception.GetType().FullName + ": " + exception.Message);
                report["exception"] = exception.ToString();
                report["api_dll_path"] = apiDllPath;
            }
            report["success"] = GetString(report, "status", "").EndsWith("PASSED", StringComparison.Ordinal);

            string directory = Path.GetDirectoryName(resultPath);
            if (!String.IsNullOrWhiteSpace(directory))
            {
                Directory.CreateDirectory(directory);
            }
            File.WriteAllText(resultPath, Json.Serialize(report));
            Console.WriteLine(Json.Serialize(report));
            return (bool)report["success"] ? 0 : 1;
        }

        private static Assembly ResolveRuntimeApi(object sender, ResolveEventArgs args)
        {
            string requested = new AssemblyName(args.Name).Name;
            if (!String.Equals(requested, Path.GetFileNameWithoutExtension(apiDllPath), StringComparison.OrdinalIgnoreCase))
            {
                return null;
            }
            return File.Exists(apiDllPath) ? Assembly.LoadFrom(apiDllPath) : null;
        }

        internal static Dictionary<string, object> NewReport(string status, string action)
        {
            return new Dictionary<string, object>
            {
                { "status", status },
                { "action", action },
                { "timestamp", DateTime.Now.ToString("s") },
                { "errors", new List<string>() },
                { "warnings", new List<string>() }
            };
        }

        internal static void AddError(Dictionary<string, object> report, string message)
        {
            ((List<string>)report["errors"]).Add(message);
        }

        internal static void AddWarning(Dictionary<string, object> report, string message)
        {
            ((List<string>)report["warnings"]).Add(message);
        }

        internal static string GetString(Dictionary<string, object> payload, string key, string fallback)
        {
            object value;
            if (payload != null && payload.TryGetValue(key, out value) && value != null)
            {
                string text = value.ToString();
                return String.IsNullOrWhiteSpace(text) ? fallback : text;
            }
            return fallback;
        }

        /// <summary>Progreso "[PLCSIM RUNTIME] ..." a stderr; stdout queda para el JSON final.</summary>
        internal static void Log(string message)
        {
            Console.Error.WriteLine("[PLCSIM RUNTIME] " + message);
        }

        /// <summary>
        /// Indices de las instancias registradas cuyo nombre coincide EXACTAMENTE (sin distinguir
        /// mayusculas, sin espacios extremos) con el pedido. 0 = no encontrada, &gt;1 = ambigua.
        /// Nunca coincidencia parcial: "TESIS_PLC_SIM" no selecciona "TESIS_PLC_SIM_2".
        /// </summary>
        internal static List<int> SelectInstances(IList<string> registeredNames, string requestedName)
        {
            List<int> matches = new List<int>();
            string wanted = (requestedName ?? "").Trim();
            if (wanted.Length == 0)
            {
                return matches;
            }
            for (int index = 0; index < registeredNames.Count; index++)
            {
                if (String.Equals((registeredNames[index] ?? "").Trim(), wanted, StringComparison.OrdinalIgnoreCase))
                {
                    matches.Add(index);
                }
            }
            return matches;
        }

        /// <summary>Adaptadores de Windows cuyo nombre o descripcion CONTIENE el patron configurado.</summary>
        internal static List<int> SelectAdapters(IList<string[]> adapters, string pattern)
        {
            List<int> matches = new List<int>();
            string wanted = (pattern ?? "").Trim();
            if (wanted.Length == 0)
            {
                return matches;
            }
            for (int index = 0; index < adapters.Count; index++)
            {
                foreach (string field in adapters[index])
                {
                    if ((field ?? "").IndexOf(wanted, StringComparison.OrdinalIgnoreCase) >= 0)
                    {
                        matches.Add(index);
                        break;
                    }
                }
            }
            return matches;
        }

        /// <summary>
        /// Lectura de la red de Windows (System.Net.NetworkInformation, solo lectura). No usa
        /// netsh/WMI y no modifica nada: solo reporta el adaptador cuyo nombre/descripcion
        /// contiene el patron (p.ej. "PLCSIM Virtual Ethernet Adapter") y sus IPv4.
        /// </summary>
        internal static Dictionary<string, object> ReadWindowsAdapter(string pattern)
        {
            Dictionary<string, object> result = new Dictionary<string, object>
            {
                { "match_pattern", pattern },
                { "source", "System.Net.NetworkInformation.NetworkInterface" },
                { "found", false },
                { "ambiguous", false },
                { "candidates", new List<object>() }
            };
            NetworkInterface[] interfaces = NetworkInterface.GetAllNetworkInterfaces();
            List<string[]> descriptors = interfaces.Select(item => new[] { item.Name, item.Description }).ToList();
            List<int> matches = SelectAdapters(descriptors, pattern);
            List<object> candidates = (List<object>)result["candidates"];
            foreach (int index in matches)
            {
                NetworkInterface item = interfaces[index];
                List<object> addresses = new List<object>();
                foreach (UnicastIPAddressInformation unicast in item.GetIPProperties().UnicastAddresses)
                {
                    if (unicast.Address.AddressFamily != AddressFamily.InterNetwork)
                    {
                        continue;
                    }
                    addresses.Add(new Dictionary<string, object>
                    {
                        { "ip", unicast.Address.ToString() },
                        { "subnet_mask", unicast.IPv4Mask == null ? null : unicast.IPv4Mask.ToString() }
                    });
                }
                candidates.Add(new Dictionary<string, object>
                {
                    { "name", item.Name },
                    { "description", item.Description },
                    { "operational_status", item.OperationalStatus.ToString() },
                    { "ipv4", addresses }
                });
            }
            result["found"] = candidates.Count == 1;
            result["ambiguous"] = candidates.Count > 1;
            if (candidates.Count == 1)
            {
                Dictionary<string, object> chosen = (Dictionary<string, object>)candidates[0];
                result["name"] = chosen["name"];
                result["description"] = chosen["description"];
                result["operational_status"] = chosen["operational_status"];
                List<object> ipv4 = (List<object>)chosen["ipv4"];
                Dictionary<string, object> first = ipv4.Count > 0 ? (Dictionary<string, object>)ipv4[0] : null;
                result["ip"] = first == null ? null : first["ip"];
                result["subnet_mask"] = first == null ? null : first["subnet_mask"];
            }
            return result;
        }

        // ------------------------------------------------------------------------------------
        // Fase 2B: verificacion PURA de una senal contra los tags del programa cargado en PLCSIM.
        // Sin tipos de la Runtime API, para poder probarla en self_test sin PLCSIM.
        // ------------------------------------------------------------------------------------

        internal sealed class TagMeta
        {
            public string Name;
            public string Area;
            public uint Offset;
            public byte Bit;
            public string Primitive;
        }

        internal const string KindProcessVariable = "PROCESS_VARIABLE";
        // Proposito obligatorio para escribir variables internas: solo el Oracle de Experimentacion.
        internal const string InternalWritePurpose = "EXPERIMENT_ORACLE";
        internal const double DefaultRealTolerance = 0.001;

        internal sealed class SignalRequest
        {
            public string Name;
            public string Address;
            public string Area;
            public uint Offset;
            public byte Bit;
            public string DataType;
            // Variables internas (estaticas del DB de instancia): se acceden SOLO por nombre Runtime.
            public string Kind;
            public bool Writable;
            public bool HasRestore;
            public object RestoreValue;
            // Variable interna: DB + miembro congelados por el ensayo; el nombre Runtime REAL se resuelve
            // contra TagInfos del programa cargado (nunca se asume su formato).
            public string Db;
            public string Member;
            public string RuntimeName;

            public string ApiName
            {
                get { return String.IsNullOrEmpty(RuntimeName) ? Name : RuntimeName; }
            }

            public bool IsProcessVariable
            {
                get { return String.Equals(Kind, KindProcessVariable, StringComparison.Ordinal); }
            }

            public bool IsReal
            {
                get { return String.Equals(DataType, "REAL", StringComparison.OrdinalIgnoreCase); }
            }
        }

        internal static SignalRequest ParseSignal(object raw)
        {
            Dictionary<string, object> payload = raw as Dictionary<string, object> ?? new Dictionary<string, object>();
            object offset, bit, writable, restore;
            payload.TryGetValue("offset", out offset);
            payload.TryGetValue("bit", out bit);
            payload.TryGetValue("writable", out writable);
            bool hasRestore = payload.TryGetValue("restore_value", out restore) && restore != null;
            return new SignalRequest
            {
                Name = GetString(payload, "name", ""),
                Address = GetString(payload, "address", ""),
                Area = GetString(payload, "area", ""),
                Offset = offset == null ? UInt32.MaxValue : Convert.ToUInt32(offset),
                Bit = bit == null ? (byte)255 : Convert.ToByte(bit),
                DataType = GetString(payload, "data_type", ""),
                Kind = GetString(payload, "kind", ""),
                Writable = writable is bool && (bool)writable,
                HasRestore = hasRestore,
                RestoreValue = restore,
                Db = GetString(payload, "db", ""),
                Member = GetString(payload, "member", "")
            };
        }

        private static string StripQuotes(string name)
        {
            return (name ?? "").Replace("\"", "");
        }

        /// <summary>
        /// Resuelve el nombre Runtime de una variable interna: el UNICO tag de area DataBlock cuyo nombre,
        /// sin comillas, es "&lt;db&gt;.&lt;miembro&gt;" (comparacion exacta). 0 -> no esta en el programa;
        /// &gt;1 -> ambiguo. Sin db/miembro se usa el nombre tal cual (busqueda exacta).
        /// </summary>
        internal static string ResolveRuntimeName(Dictionary<string, TagMeta> tagsByName, SignalRequest signal, out TagMeta tag, out string detail)
        {
            detail = "";
            tag = null;
            if (String.IsNullOrEmpty(signal.Db) || String.IsNullOrEmpty(signal.Member))
            {
                if (!String.IsNullOrWhiteSpace(signal.Name) && tagsByName.TryGetValue(signal.Name, out tag))
                {
                    signal.RuntimeName = tag.Name;
                    return null;
                }
                detail = "'" + signal.Name + "' no existe en el programa cargado en PLCSIM (TagInfos con DB).";
                return "PLCSIM_SIGNAL_NOT_IN_CURRENT_PROGRAM";
            }
            string wanted = StripQuotes(signal.Db) + "." + StripQuotes(signal.Member);
            List<TagMeta> candidates = tagsByName.Values
                .Where(t => String.Equals(t.Area, "DataBlock", StringComparison.Ordinal)
                            && String.Equals(StripQuotes(t.Name), wanted, StringComparison.Ordinal))
                .ToList();
            if (candidates.Count == 0)
            {
                detail = "'" + wanted + "' no existe en el programa cargado en PLCSIM (TagInfos con DB).";
                return "PLCSIM_SIGNAL_NOT_IN_CURRENT_PROGRAM";
            }
            if (candidates.Count > 1)
            {
                detail = "'" + wanted + "' es ambiguo en PLCSIM: " + String.Join(", ", candidates.Select(t => t.Name)) + ".";
                return "PLCSIM_SIGNAL_AMBIGUOUS";
            }
            tag = candidates[0];
            signal.RuntimeName = tag.Name;
            return null;
        }

        /// <summary>
        /// null si la variable interna puede usarse; si no, el codigo de error. Reglas: kind
        /// PROCESS_VARIABLE; el nombre Runtime debe existir en el programa CARGADO (TagInfos con DB)
        /// en el area DataBlock; BOOL &lt;-&gt; Bool y REAL &lt;-&gt; Float; solo se escribe si el ensayo la
        /// declaro escribible (rol INPUT con binding PROCESS_VARIABLE) y el proposito es el Oracle.
        /// </summary>
        internal static string VerifyProcessVariable(Dictionary<string, TagMeta> tagsByName, SignalRequest signal, bool forWrite,
            string purpose, out string detail)
        {
            detail = "";
            if (!signal.IsProcessVariable)
            {
                detail = signal.Name + ": no es una variable de proceso.";
                return "PLCSIM_SIGNAL_TYPE_UNSUPPORTED";
            }
            string expectedPrimitive = String.Equals(signal.DataType, "BOOL", StringComparison.OrdinalIgnoreCase) ? "Bool"
                : (signal.IsReal ? "Float" : null);
            if (expectedPrimitive == null)
            {
                detail = signal.Name + ": tipo '" + signal.DataType + "' no soportado para variables internas (BOOL/REAL).";
                return "PLCSIM_SIGNAL_TYPE_UNSUPPORTED";
            }
            if (forWrite && !signal.Writable)
            {
                detail = signal.Name + ": la variable interna no es escribible en este ensayo (solo roles INPUT PROCESS_VARIABLE).";
                return "PLCSIM_IO_WRITE_NOT_ALLOWED";
            }
            if (forWrite && !String.Equals(purpose, InternalWritePurpose, StringComparison.Ordinal))
            {
                detail = signal.Name + ": escritura interna solo durante la ejecucion del Oracle (purpose=" + purpose + ").";
                return "PLCSIM_IO_WRITE_NOT_ALLOWED";
            }
            TagMeta tag;
            string resolution = ResolveRuntimeName(tagsByName, signal, out tag, out detail);
            if (resolution != null)
            {
                return resolution;
            }
            if (!String.Equals(tag.Area, "DataBlock", StringComparison.Ordinal))
            {
                detail = "'" + signal.Name + "' esta en el area " + tag.Area + ", no en un DB.";
                return "PLCSIM_SIGNAL_NOT_IN_CURRENT_PROGRAM";
            }
            if (!String.Equals(tag.Primitive, expectedPrimitive, StringComparison.Ordinal))
            {
                detail = "'" + signal.Name + "' es " + tag.Primitive + " en PLCSIM; el ensayo espera " + signal.DataType + ".";
                return "PLCSIM_SIGNAL_TYPE_UNSUPPORTED";
            }
            return null;
        }

        /// <summary>Readback de un valor pedido: BOOL exacto, REAL con tolerancia absoluta.</summary>
        internal static bool ValueMatches(object requested, object actual, bool isReal, double tolerance)
        {
            if (requested == null || actual == null)
            {
                return false;
            }
            if (isReal)
            {
                return Math.Abs(Convert.ToDouble(requested) - Convert.ToDouble(actual)) <= tolerance;
            }
            return requested is bool && actual is bool && (bool)requested == (bool)actual;
        }

        /// <summary>
        /// Requisito de una precondicion (como oracle_runner.value_matches): BOOL igualdad; numero exacto
        /// (1e-6); {approx, tolerance}; {min, max}.
        /// </summary>
        internal static bool RequirementMatches(object expected, object actual)
        {
            if (actual == null)
            {
                return false;
            }
            if (expected is bool || actual is bool)
            {
                return expected is bool && actual is bool && (bool)expected == (bool)actual;
            }
            Dictionary<string, object> spec = expected as Dictionary<string, object>;
            double value = Convert.ToDouble(actual);
            if (spec != null)
            {
                if (spec.ContainsKey("approx"))
                {
                    double tolerance = spec.ContainsKey("tolerance") ? Convert.ToDouble(spec["tolerance"]) : 0.0;
                    return Math.Abs(value - Convert.ToDouble(spec["approx"])) <= tolerance;
                }
                double low = spec.ContainsKey("min") ? Convert.ToDouble(spec["min"]) : Double.NegativeInfinity;
                double high = spec.ContainsKey("max") ? Convert.ToDouble(spec["max"]) : Double.PositiveInfinity;
                return low <= value && value <= high;
            }
            return Math.Abs(value - Convert.ToDouble(expected)) <= 1e-6;
        }

        /// <summary>
        /// null si la senal puede usarse; si no, el codigo de error. Reglas: solo BOOL; escritura
        /// solo sobre el area Input; el tag debe existir en el programa CARGADO con la misma
        /// area/byte/bit que el snapshot del ensayo (si no, el programa en PLCSIM no es el del ensayo).
        /// </summary>
        internal static string VerifySignal(Dictionary<string, TagMeta> tagsByName, SignalRequest signal, bool forWrite, out string detail)
        {
            detail = "";
            bool isInput = String.Equals(signal.Area, "Input", StringComparison.Ordinal);
            bool isOutput = String.Equals(signal.Area, "Output", StringComparison.Ordinal);
            if (forWrite && !isInput)
            {
                detail = signal.Name + " (" + signal.Address + ") no es una entrada: solo se escriben entradas.";
                return "PLCSIM_IO_WRITE_NOT_ALLOWED";
            }
            if (!isInput && !isOutput)
            {
                detail = signal.Name + ": area '" + signal.Area + "' no soportada (solo Input/Output).";
                return "PLCSIM_SIGNAL_TYPE_UNSUPPORTED";
            }
            if (!String.Equals(signal.DataType, "BOOL", StringComparison.OrdinalIgnoreCase) || signal.Bit > 7)
            {
                detail = signal.Name + ": tipo '" + signal.DataType + "' no soportado (Fase 2B: solo BOOL).";
                return "PLCSIM_SIGNAL_TYPE_UNSUPPORTED";
            }
            TagMeta tag;
            if (String.IsNullOrWhiteSpace(signal.Name) || !tagsByName.TryGetValue(signal.Name, out tag))
            {
                detail = "'" + signal.Name + "' no existe en el programa cargado en PLCSIM.";
                return "PLCSIM_SIGNAL_NOT_IN_CURRENT_PROGRAM";
            }
            if (!String.Equals(tag.Area, signal.Area, StringComparison.Ordinal) || tag.Offset != signal.Offset || tag.Bit != signal.Bit)
            {
                detail = "'" + signal.Name + "' esta en " + tag.Area + " " + tag.Offset + "." + tag.Bit
                    + " en PLCSIM, pero el ensayo lo espera en " + signal.Address + ".";
                return "PLCSIM_SIGNAL_NOT_IN_CURRENT_PROGRAM";
            }
            if (!String.Equals(tag.Primitive, "Bool", StringComparison.Ordinal))
            {
                detail = "'" + signal.Name + "' es " + tag.Primitive + " en PLCSIM (solo BOOL).";
                return "PLCSIM_SIGNAL_TYPE_UNSUPPORTED";
            }
            return null;
        }

        private static Dictionary<string, object> RunSelfTest()
        {
            Dictionary<string, object> report = NewReport("PLCSIM_RUNTIME_SELF_TEST_PASSED", "self_test");
            List<object> checks = new List<object>();
            report["checks"] = checks;

            Action<string, int[], int[]> check = (label, expected, actual) =>
            {
                bool passed = expected.SequenceEqual(actual);
                checks.Add(new Dictionary<string, object>
                {
                    { "check", label },
                    { "expected", String.Join(",", expected) },
                    { "actual", String.Join(",", actual) },
                    { "passed", passed }
                });
                if (!passed)
                {
                    report["status"] = "PLCSIM_RUNTIME_SELF_TEST_FAILED";
                }
            };

            string[] registered = { "Otra_Instancia", "TESIS_PLC_SIM", "TESIS_PLC_SIM_2" };
            check("instance.unique", new[] { 1 }, SelectInstances(registered, "TESIS_PLC_SIM").ToArray());
            check("instance.case_and_trim", new[] { 1 }, SelectInstances(registered, "  tesis_plc_sim ").ToArray());
            check("instance.absent", new int[0], SelectInstances(registered, "NO_EXISTE").ToArray());
            check("instance.no_partial_match", new int[0], SelectInstances(registered, "TESIS").ToArray());
            check("instance.empty_request", new int[0], SelectInstances(registered, "").ToArray());
            check("instance.duplicate", new[] { 0, 1 }, SelectInstances(new[] { "TESIS_PLC_SIM", "tesis_plc_sim" }, "TESIS_PLC_SIM").ToArray());
            check("instance.none_registered", new int[0], SelectInstances(new string[0], "TESIS_PLC_SIM").ToArray());

            List<string[]> adapters = new List<string[]>
            {
                new[] { "Wi-Fi", "Intel(R) Wi-Fi 6 AX201" },
                new[] { "Ethernet 3", "Siemens PLCSIM Virtual Ethernet Adapter" }
            };
            check("adapter.by_description", new[] { 1 }, SelectAdapters(adapters, "PLCSIM Virtual Ethernet Adapter").ToArray());
            check("adapter.by_name", new[] { 1 }, SelectAdapters(adapters, "ethernet 3").ToArray());
            check("adapter.empty_pattern", new int[0], SelectAdapters(adapters, " ").ToArray());

            Dictionary<string, TagMeta> tags = new Dictionary<string, TagMeta>(StringComparer.Ordinal)
            {
                { "I_Start", new TagMeta { Name = "I_Start", Area = "Input", Offset = 16, Bit = 0, Primitive = "Bool" } },
                { "Q_Motor", new TagMeta { Name = "Q_Motor", Area = "Output", Offset = 8, Bit = 0, Primitive = "Bool" } },
                { "I_Level", new TagMeta { Name = "I_Level", Area = "Input", Offset = 16, Bit = 2, Primitive = "Int16" } }
            };
            Func<string, string, uint, byte, string, SignalRequest> sig = (name, area, offset, bit, type) =>
                new SignalRequest { Name = name, Address = area + offset + "." + bit, Area = area, Offset = offset, Bit = bit, DataType = type };
            Action<string, string, string> verdict = (label, expected, actual) =>
            {
                bool passed = String.Equals(expected ?? "OK", actual ?? "OK", StringComparison.Ordinal);
                checks.Add(new Dictionary<string, object>
                {
                    { "check", label }, { "expected", expected ?? "OK" }, { "actual", actual ?? "OK" }, { "passed", passed }
                });
                if (!passed)
                {
                    report["status"] = "PLCSIM_RUNTIME_SELF_TEST_FAILED";
                }
            };
            string ignored;
            verdict("signal.write_input_ok", null, VerifySignal(tags, sig("I_Start", "Input", 16, 0, "BOOL"), true, out ignored));
            verdict("signal.read_output_ok", null, VerifySignal(tags, sig("Q_Motor", "Output", 8, 0, "BOOL"), false, out ignored));
            verdict("signal.write_output_denied", "PLCSIM_IO_WRITE_NOT_ALLOWED", VerifySignal(tags, sig("Q_Motor", "Output", 8, 0, "BOOL"), true, out ignored));
            verdict("signal.write_marker_denied", "PLCSIM_IO_WRITE_NOT_ALLOWED", VerifySignal(tags, sig("M_Aux", "Marker", 0, 0, "BOOL"), true, out ignored));
            verdict("signal.not_in_program", "PLCSIM_SIGNAL_NOT_IN_CURRENT_PROGRAM", VerifySignal(tags, sig("I_Other", "Input", 16, 5, "BOOL"), true, out ignored));
            verdict("signal.address_mismatch", "PLCSIM_SIGNAL_NOT_IN_CURRENT_PROGRAM", VerifySignal(tags, sig("I_Start", "Input", 16, 3, "BOOL"), true, out ignored));
            verdict("signal.type_request_int", "PLCSIM_SIGNAL_TYPE_UNSUPPORTED", VerifySignal(tags, sig("I_Start", "Input", 16, 0, "INT"), true, out ignored));
            verdict("signal.type_runtime_int", "PLCSIM_SIGNAL_TYPE_UNSUPPORTED", VerifySignal(tags, sig("I_Level", "Input", 16, 2, "BOOL"), true, out ignored));

            // Variables internas (PROCESS_VARIABLE): verificacion pura contra TagInfos con DB.
            Dictionary<string, TagMeta> dbTags = new Dictionary<string, TagMeta>(StringComparer.Ordinal)
            {
                { "DB_PLC_PRG.Level_PV", new TagMeta { Name = "DB_PLC_PRG.Level_PV", Area = "DataBlock", Primitive = "Float" } },
                { "DB_PLC_PRG.PID_Enable", new TagMeta { Name = "DB_PLC_PRG.PID_Enable", Area = "DataBlock", Primitive = "Bool" } },
                { "I_Start", new TagMeta { Name = "I_Start", Area = "Input", Offset = 16, Bit = 0, Primitive = "Bool" } }
            };
            Func<string, string, bool, SignalRequest> pv = (name, type, writable) =>
                new SignalRequest { Name = name, DataType = type, Kind = KindProcessVariable, Writable = writable };
            verdict("pv.read_real_ok", null, VerifyProcessVariable(dbTags, pv("DB_PLC_PRG.Level_PV", "REAL", false), false, "", out ignored));
            verdict("pv.read_bool_ok", null, VerifyProcessVariable(dbTags, pv("DB_PLC_PRG.PID_Enable", "BOOL", false), false, "", out ignored));
            verdict("pv.write_real_ok", null, VerifyProcessVariable(dbTags, pv("DB_PLC_PRG.Level_PV", "REAL", true), true, InternalWritePurpose, out ignored));
            verdict("pv.write_not_writable", "PLCSIM_IO_WRITE_NOT_ALLOWED", VerifyProcessVariable(dbTags, pv("DB_PLC_PRG.PID_Enable", "BOOL", false), true, InternalWritePurpose, out ignored));
            verdict("pv.write_without_oracle_purpose", "PLCSIM_IO_WRITE_NOT_ALLOWED", VerifyProcessVariable(dbTags, pv("DB_PLC_PRG.Level_PV", "REAL", true), true, "", out ignored));
            verdict("pv.type_mismatch", "PLCSIM_SIGNAL_TYPE_UNSUPPORTED", VerifyProcessVariable(dbTags, pv("DB_PLC_PRG.Level_PV", "BOOL", false), false, "", out ignored));
            verdict("pv.unsupported_type", "PLCSIM_SIGNAL_TYPE_UNSUPPORTED", VerifyProcessVariable(dbTags, pv("DB_PLC_PRG.Level_PV", "INT", false), false, "", out ignored));
            verdict("pv.not_in_program", "PLCSIM_SIGNAL_NOT_IN_CURRENT_PROGRAM", VerifyProcessVariable(dbTags, pv("DB_PLC_PRG.Level_SP", "REAL", false), false, "", out ignored));
            verdict("pv.not_a_db_tag", "PLCSIM_SIGNAL_NOT_IN_CURRENT_PROGRAM", VerifyProcessVariable(dbTags, pv("I_Start", "BOOL", false), false, "", out ignored));
            // Resolucion del nombre Runtime: formato descubierto en TagInfos (con o sin comillas), nunca asumido.
            Func<string, string, SignalRequest> member = (db, name) =>
                new SignalRequest { Name = db + "." + name, DataType = "REAL", Kind = KindProcessVariable, Db = db, Member = name };
            Dictionary<string, TagMeta> quoted = new Dictionary<string, TagMeta>(StringComparer.Ordinal)
            {
                { "\"DB_PLC_PRG\".Level_PV", new TagMeta { Name = "\"DB_PLC_PRG\".Level_PV", Area = "DataBlock", Primitive = "Float" } },
                { "DB_OTHER.Level_PV", new TagMeta { Name = "DB_OTHER.Level_PV", Area = "DataBlock", Primitive = "Float" } }
            };
            TagMeta resolvedTag;
            SignalRequest quotedSignal = member("DB_PLC_PRG", "Level_PV");
            verdict("pv.resolve_quoted_format", null, ResolveRuntimeName(quoted, quotedSignal, out resolvedTag, out ignored));
            verdict("pv.resolve_quoted_runtime_name", "\"DB_PLC_PRG\".Level_PV", quotedSignal.RuntimeName);
            SignalRequest plainSignal = member("DB_PLC_PRG", "Level_PV");
            verdict("pv.resolve_plain_format", null, ResolveRuntimeName(dbTags, plainSignal, out resolvedTag, out ignored));
            verdict("pv.resolve_plain_runtime_name", "DB_PLC_PRG.Level_PV", plainSignal.RuntimeName);
            verdict("pv.resolve_missing_member", "PLCSIM_SIGNAL_NOT_IN_CURRENT_PROGRAM", ResolveRuntimeName(quoted, member("DB_PLC_PRG", "Level_SP"), out resolvedTag, out ignored));
            verdict("pv.resolve_never_other_db", "PLCSIM_SIGNAL_NOT_IN_CURRENT_PROGRAM", ResolveRuntimeName(quoted, member("DB_X", "Level_PV"), out resolvedTag, out ignored));
            Dictionary<string, TagMeta> both = new Dictionary<string, TagMeta>(quoted, StringComparer.Ordinal)
            {
                { "DB_PLC_PRG.Level_PV", new TagMeta { Name = "DB_PLC_PRG.Level_PV", Area = "DataBlock", Primitive = "Float" } }
            };
            verdict("pv.resolve_ambiguous", "PLCSIM_SIGNAL_AMBIGUOUS", ResolveRuntimeName(both, member("DB_PLC_PRG", "Level_PV"), out resolvedTag, out ignored));
            Action<string, bool, bool> truth = (label, expected, actual) => verdict(label, expected ? "TRUE" : "FALSE", actual ? "TRUE" : "FALSE");
            truth("pv.readback_real_within_tolerance", true, ValueMatches(60.0, 60.0004f, true, DefaultRealTolerance));
            truth("pv.readback_real_outside_tolerance", false, ValueMatches(60.0, 60.01, true, DefaultRealTolerance));
            truth("pv.readback_bool", true, ValueMatches(true, true, false, 0));
            truth("require.approx", true, RequirementMatches(new Dictionary<string, object> { { "approx", 60.0 }, { "tolerance", 0.01 } }, 60.005));
            truth("require.approx_out", false, RequirementMatches(new Dictionary<string, object> { { "approx", 60.0 }, { "tolerance", 0.01 } }, 60.02));
            truth("require.range", true, RequirementMatches(new Dictionary<string, object> { { "min", 0.0 }, { "max", 100.0 } }, 50.0));
            truth("require.bool", false, RequirementMatches(false, true));
            return report;
        }
    }

    /// <summary>
    /// Todo lo que toca tipos de la Runtime API vive aqui: si la DLL no se puede cargar, el JIT
    /// falla al compilar Execute y Main lo clasifica como PLCSIM_API_NOT_AVAILABLE.
    /// </summary>
    internal static class RuntimeReader
    {
        [MethodImpl(MethodImplOptions.NoInlining)]
        internal static Dictionary<string, object> Execute(Dictionary<string, object> request, bool openInstance, string dllPath)
        {
            string action = openInstance ? "runtime_status" : "status";
            Dictionary<string, object> report = Program.NewReport("PLCSIM_RUNTIME_ERROR", action);
            string instanceName = Program.GetString(request, "instance_name", "");
            report["instance_name_requested"] = instanceName;
            report["instance_found"] = false;
            report["registered_instances"] = new List<object>();

            Dictionary<string, object> api = DescribeApi(dllPath);
            report["api"] = api;

            string adapterPattern = Program.GetString(request, "windows_adapter_match", "");
            try
            {
                report["windows_adapter"] = Program.ReadWindowsAdapter(adapterPattern);
            }
            catch (Exception exception)
            {
                report["windows_adapter"] = new Dictionary<string, object> { { "match_pattern", adapterPattern }, { "found", false }, { "error", exception.Message } };
            }

            Program.Log("Connecting to Runtime Manager (API " + api["assembly_version"] + ")");
            try
            {
                bool available = SimulationRuntimeManager.IsRuntimeManagerAvailable;
                api["runtime_manager_available"] = available;
                api["is_initialized"] = SimulationRuntimeManager.IsInitialized;
                api["runtime_version"] = FormatVersion(SimulationRuntimeManager.Version);
                if (!available)
                {
                    report["status"] = "PLCSIM_RUNTIME_UNAVAILABLE";
                    Program.AddError(report, "El Runtime Manager de PLCSIM Advanced no esta disponible (PLCSIM Advanced no iniciado).");
                    Program.Log("Runtime Manager not available");
                    return report;
                }

                SInstanceInfo[] infos = SimulationRuntimeManager.RegisteredInstanceInfo ?? new SInstanceInfo[0];
                List<object> registered = (List<object>)report["registered_instances"];
                foreach (SInstanceInfo info in infos)
                {
                    registered.Add(new Dictionary<string, object> { { "id", info.ID }, { "name", info.Name } });
                }
                string names = infos.Length == 0 ? "(ninguna)" : String.Join(", ", infos.Select(info => info.Name));
                Program.Log("Registered instances: " + names);

                List<int> matches = Program.SelectInstances(infos.Select(info => info.Name).ToList(), instanceName);
                if (matches.Count == 0)
                {
                    report["status"] = "PLCSIM_INSTANCE_NOT_FOUND";
                    Program.AddError(report, "Instancia '" + instanceName + "' no encontrada. Instancias registradas: " + names + ".");
                    Program.Log("Instance '" + instanceName + "' NOT FOUND");
                    return report;
                }
                if (matches.Count > 1)
                {
                    report["status"] = "PLCSIM_INSTANCE_AMBIGUOUS";
                    Program.AddError(report, "Hay " + matches.Count + " instancias llamadas '" + instanceName + "': " + names + ".");
                    Program.Log("Instance '" + instanceName + "' AMBIGUOUS");
                    return report;
                }

                SInstanceInfo selected = infos[matches[0]];
                report["instance_found"] = true;
                report["instance_id"] = selected.ID;
                Program.Log("Instance found: " + selected.Name + " (ID " + selected.ID + ")");
                if (!openInstance)
                {
                    report["status"] = "PLCSIM_RUNTIME_PASSED";
                    return report;
                }

                IInstance instance = SimulationRuntimeManager.CreateInterface(selected.Name);
                Dictionary<string, object> details = ReadInstance(instance);
                report["instance"] = details;
                Program.Log("OperatingState: " + details["operating_state"]);
                report["status"] = "PLCSIM_RUNTIME_PASSED";
                return report;
            }
            catch (SimulationRuntimeException exception)
            {
                report["status"] = "PLCSIM_RUNTIME_ERROR";
                report["runtime_error_code"] = exception.RuntimeErrorCode.ToString();
                Program.AddError(report, "SimulationRuntimeException (" + exception.RuntimeErrorCode + "): " + exception.Message);
                return report;
            }
            catch (Exception exception)
            {
                Exception root = exception is TypeInitializationException && exception.InnerException != null ? exception.InnerException : exception;
                bool initFailure = root is SimulationInitializationException;
                report["status"] = initFailure ? "PLCSIM_RUNTIME_UNAVAILABLE" : "PLCSIM_RUNTIME_ERROR";
                Program.AddError(report, root.GetType().FullName + ": " + root.Message);
                report["exception"] = root.ToString();
                return report;
            }
            finally
            {
                try
                {
                    if (SimulationRuntimeManager.IsInitialized)
                    {
                        SimulationRuntimeManager.Shutdown();
                    }
                }
                catch (Exception)
                {
                    // Cierre de la conexion con el Runtime Manager: best effort.
                }
            }
        }

        private static Dictionary<string, object> ReadInstance(IInstance instance)
        {
            Dictionary<string, object> details = new Dictionary<string, object>();
            List<string> readErrors = new List<string>();
            TryRead(details, readErrors, "id", () => instance.ID);
            TryRead(details, readErrors, "name", () => instance.Name);
            TryRead(details, readErrors, "operating_state", () => instance.OperatingState.ToString());
            TryRead(details, readErrors, "cpu_type", () => instance.CPUType.ToString());
            TryRead(details, readErrors, "controller_name", () => instance.ControllerName);
            TryRead(details, readErrors, "controller_short_designation", () => instance.ControllerShortDesignation);
            TryRead(details, readErrors, "communication_interface", () => instance.CommunicationInterface.ToString());
            TryRead(details, readErrors, "license_status", () => instance.LicenseStatus.ToString());
            TryRead(details, readErrors, "controller_ip", () => (instance.ControllerIP ?? new string[0]).ToList());
            TryRead(details, readErrors, "ip_suites", () =>
            {
                List<object> suites = new List<object>();
                SIPSuite4[] raw = instance.ControllerIPSuite4 ?? new SIPSuite4[0];
                for (int index = 0; index < raw.Length; index++)
                {
                    // El indice es el de la API; V5 no documenta su correspondencia con X1/X2.
                    suites.Add(new Dictionary<string, object>
                    {
                        { "index", index },
                        { "ip", raw[index].IPAddress.IPString },
                        { "subnet_mask", raw[index].SubnetMask.IPString },
                        { "default_gateway", raw[index].DefaultGateway.IPString }
                    });
                }
                return suites;
            });
            details["read_errors"] = readErrors;
            return details;
        }

        private static void TryRead(Dictionary<string, object> target, List<string> errors, string key, Func<object> getter)
        {
            try
            {
                target[key] = getter();
            }
            catch (Exception exception)
            {
                target[key] = null;
                errors.Add(key + ": " + exception.GetType().Name + ": " + exception.Message);
            }
        }

        private static Dictionary<string, object> DescribeApi(string dllPath)
        {
            Assembly assembly = typeof(SimulationRuntimeManager).Assembly;
            string fileVersion = null;
            try
            {
                fileVersion = FileVersionInfo.GetVersionInfo(assembly.Location).FileVersion;
            }
            catch (Exception)
            {
                // Solo informativo.
            }
            return new Dictionary<string, object>
            {
                { "dll_path", assembly.Location },
                { "requested_dll_path", dllPath },
                { "assembly_version", assembly.GetName().Version.ToString() },
                { "file_version", fileVersion },
                { "clr_runtime", assembly.ImageRuntimeVersion },
                { "process_is_64bit", Environment.Is64BitProcess }
            };
        }

        private static string FormatVersion(uint version)
        {
            // Valor crudo de SimulationRuntimeManager.Version: su codificacion no esta
            // documentada en SimulationRuntimeApi.h, asi que no se interpreta.
            return "0x" + version.ToString("X");
        }
    }
    /// <summary>
    /// Fase 2B: Runtime I/O BOOL. Acceso PRINCIPAL por direccion (InputArea/OutputArea ReadBit y
    /// InputArea.WriteBit, con byte/bit tomados del snapshot del ensayo); el NOMBRE se usa como
    /// verificacion obligatoria (el tag debe existir en el programa cargado con la misma
    /// direccion) y como segundo canal de readback (ReadBool).
    /// P01-P12 (variables internas, kind PROCESS_VARIABLE): estaticas BOOL/REAL del DB de instancia,
    /// SOLO por nombre Runtime resuelto contra TagInfos (UpdateTagList IODB): ReadBool/ReadFloat y
    /// WriteBool/WriteFloat. Se escriben unicamente las marcadas writable (rol INPUT del Oracle) con
    /// purpose EXPERIMENT_ORACLE, con readback (REAL con tolerancia) y restauracion final verificada.
    /// discover_tags: listado de solo lectura de los tags de DB (formato real del nombre).
    /// Nunca: salidas, marcas, timers, contadores, IP ni estado de CPU. Toda escritura exige target
    /// PLCSIM_ADVANCED, la instancia pedida y OperatingState == Run.
    /// </summary>
    internal static class RuntimeIO
    {
        [MethodImpl(MethodImplOptions.NoInlining)]
        internal static Dictionary<string, object> Execute(Dictionary<string, object> request, string action)
        {
            Dictionary<string, object> report = Program.NewReport("PLCSIM_RUNTIME_ERROR", action);
            string instanceName = Program.GetString(request, "instance_name", "");
            string targetType = Program.GetString(request, "target_type", "");
            string purpose = Program.GetString(request, "purpose", "");
            bool writes = action != "read_signal" && action != "discover_tags";
            // Variables internas (estaticas de DB): la lista de tags debe incluir los DB (solo lectura de metadatos).
            bool withDataBlocks = action == "discover_tags" || GetBool(request, "process_variables");
            double realTolerance = GetDouble(request, "real_tolerance", Program.DefaultRealTolerance);
            report["purpose"] = purpose;
            report["real_tolerance"] = realTolerance;
            int settleMs = Math.Max(0, Math.Min(10000, GetInt(request, "settle_ms", 500)));
            report["instance_name"] = instanceName;
            report["target_type"] = targetType;
            report["settle_ms"] = settleMs;
            report["writes"] = new List<object>();
            report["reads"] = new List<object>();
            report["observations"] = new List<object>();

            if (writes && !String.Equals(targetType, "PLCSIM_ADVANCED", StringComparison.Ordinal))
            {
                return Deny(report, "PLCSIM_IO_WRITE_NOT_ALLOWED", "El destino no es PLCSIM_ADVANCED (" + targetType + "): nunca se escribe en un PLC fisico.");
            }

            IInstance instance = null;
            List<Program.SignalRequest> writtenInputs = new List<Program.SignalRequest>();
            // Variable interna escrita -> valor original leido ANTES de la primera escritura.
            Dictionary<string, KeyValuePair<Program.SignalRequest, object>> writtenVariables =
                new Dictionary<string, KeyValuePair<Program.SignalRequest, object>>(StringComparer.Ordinal);
            try
            {
                if (!SimulationRuntimeManager.IsRuntimeManagerAvailable)
                {
                    return Deny(report, writes ? "PLCSIM_IO_WRITE_NOT_ALLOWED" : "PLCSIM_RUNTIME_UNAVAILABLE", "Runtime Manager no disponible.");
                }
                SInstanceInfo[] infos = SimulationRuntimeManager.RegisteredInstanceInfo ?? new SInstanceInfo[0];
                List<int> matches = Program.SelectInstances(infos.Select(info => info.Name).ToList(), instanceName);
                if (matches.Count != 1)
                {
                    string code = matches.Count == 0 ? "PLCSIM_INSTANCE_NOT_FOUND" : "PLCSIM_INSTANCE_AMBIGUOUS";
                    return Deny(report, writes ? "PLCSIM_IO_WRITE_NOT_ALLOWED" : code, "Instancia '" + instanceName + "': " + code + ".");
                }
                instance = SimulationRuntimeManager.CreateInterface(infos[matches[0]].Name);
                EOperatingState state = instance.OperatingState;
                report["cpu_state"] = state.ToString().ToUpperInvariant();
                if (writes && state != EOperatingState.Run)
                {
                    report["reason_code"] = "PLCSIM_CPU_NOT_RUN";
                    return Deny(report, "PLCSIM_IO_WRITE_NOT_ALLOWED", "CPU en " + state + ": solo se escribe con la CPU en RUN.");
                }

                instance.UpdateTagList(withDataBlocks ? ETagListDetails.IODB : ETagListDetails.IO, false);
                report["tag_list_details"] = withDataBlocks ? "IODB" : "IO";
                Dictionary<string, Program.TagMeta> tags = new Dictionary<string, Program.TagMeta>(StringComparer.Ordinal);
                List<STagInfo> tagInfos = (instance.TagInfos ?? new STagInfo[0]).ToList();
                foreach (STagInfo tag in tagInfos)
                {
                    tags[tag.Name] = new Program.TagMeta
                    {
                        Name = tag.Name, Area = tag.Area.ToString(), Offset = tag.Offset, Bit = tag.Bit, Primitive = tag.PrimitiveDataType.ToString()
                    };
                }
                report["program_tags"] = tags.Values.Where(t => t.Area != "DataBlock")
                    .Select(t => (object)(t.Name + "@" + t.Area + " " + t.Offset + "." + t.Bit)).ToList();

                if (action == "discover_tags")
                {
                    Discover(instance, tagInfos, Program.GetString(request, "db_name", ""), report);
                }
                else if (action == "read_signal")
                {
                    foreach (object raw in AsList(request, "signals"))
                    {
                        if (!ReadOne(instance, tags, Program.ParseSignal(raw), report, "read"))
                        {
                            return report;
                        }
                    }
                }
                else if (action == "write_input")
                {
                    bool value = GetBool(request, "value");
                    WriteOne(instance, tags, Program.ParseSignal(request["signal"]), value, settleMs, report, writtenInputs, "write");
                }
                else if (action == "restore_inputs")
                {
                    foreach (object raw in AsList(request, "signals"))
                    {
                        Program.SignalRequest signal = Program.ParseSignal(raw);
                        string detail;
                        if (Program.VerifySignal(tags, signal, true, out detail) == null)
                        {
                            writtenInputs.Add(signal);
                        }
                        else
                        {
                            Program.AddWarning(report, "restore: " + detail);
                        }
                    }
                }
                else if (action == "io_sequence")
                {
                    // Fase 3A: un unico reloj monotono para toda la secuencia (precondiciones, pasos,
                    // esperas, muestreo, limpieza). Los tiempos del Oracle se miden aqui, nunca en
                    // Python, para no confundir latencia de infraestructura con el PLC.
                    Stopwatch clock = Stopwatch.StartNew();
                    report["events"] = new List<object>();
                    report["samples"] = new List<object>();
                    int index = 0;
                    foreach (object rawStep in AsList(request, "steps"))
                    {
                        Dictionary<string, object> step = rawStep as Dictionary<string, object> ?? new Dictionary<string, object>();
                        string op = Program.GetString(step, "op", "");
                        string label = "step" + (++index) + ":" + op;
                        bool ok;
                        if (op == "write")
                        {
                            ok = WriteOne(instance, tags, Program.ParseSignal(step["signal"]), GetBool(step, "value"), settleMs, report, writtenInputs, label);
                        }
                        else if (op == "read")
                        {
                            ok = ReadOne(instance, tags, Program.ParseSignal(step["signal"]), report, label);
                        }
                        else if (op == "set")
                        {
                            ok = SetMany(instance, tags, step, clock, report, writtenInputs, writtenVariables, purpose, realTolerance, settleMs);
                        }
                        else if (op == "sample")
                        {
                            ok = Sample(instance, tags, step, clock, report, purpose);
                        }
                        else
                        {
                            report["status"] = "PLCSIM_RUNTIME_ERROR";
                            Program.AddError(report, "Paso desconocido: " + op);
                            ok = false;
                        }
                        if (!ok)
                        {
                            report["failed_step"] = Program.GetString(step, "id", label);
                            break;
                        }
                    }
                    report["sequence_duration_ms"] = clock.Elapsed.TotalMilliseconds;
                }

                if (!((List<string>)report["errors"]).Any())
                {
                    report["status"] = "PLCSIM_IO_PASSED";
                }
                return report;
            }
            catch (SimulationRuntimeException exception)
            {
                report["status"] = writes ? "PLCSIM_INPUT_WRITE_FAILED" : "PLCSIM_OUTPUT_READ_FAILED";
                report["runtime_error_code"] = exception.RuntimeErrorCode.ToString();
                Program.AddError(report, "SimulationRuntimeException (" + exception.RuntimeErrorCode + "): " + exception.Message);
                return report;
            }
            finally
            {
                // Cleanup OBLIGATORIO (io_sequence / restore_inputs, y write_input fallido): toda
                // entrada tocada vuelve a FALSE y se verifica; un fallo aqui nunca se oculta.
                bool cleanupNeeded = action == "io_sequence" || action == "restore_inputs"
                    || (action == "write_input" && GetString(report, "status") != "PLCSIM_IO_PASSED");
                if (cleanupNeeded && instance != null && writtenInputs.Count > 0)
                {
                    Cleanup(instance, writtenInputs, settleMs, report);
                }
                if (instance != null && writtenVariables.Count > 0)
                {
                    RestoreVariables(instance, writtenVariables, settleMs, realTolerance, report);
                }
                try
                {
                    if (SimulationRuntimeManager.IsInitialized)
                    {
                        SimulationRuntimeManager.Shutdown();
                    }
                }
                catch (Exception)
                {
                    // Cierre de la conexion con el Runtime Manager: best effort.
                }
            }
        }

        private static bool WriteOne(
            IInstance instance, Dictionary<string, Program.TagMeta> tags, Program.SignalRequest signal, bool value,
            int settleMs, Dictionary<string, object> report, List<Program.SignalRequest> writtenInputs, string label)
        {
            string detail;
            string error = Program.VerifySignal(tags, signal, true, out detail);
            if (error != null)
            {
                report["status"] = error;
                Program.AddError(report, detail);
                return false;
            }
            Dictionary<string, object> entry = new Dictionary<string, object>
            {
                { "label", label }, { "name", signal.Name }, { "address", signal.Address }, { "requested_value", value },
                { "timestamp", DateTime.Now.ToString("o") }
            };
            ((List<object>)report["writes"]).Add(entry);
            try
            {
                instance.InputArea.WriteBit(signal.Offset, signal.Bit, value);
            }
            catch (SimulationRuntimeException exception)
            {
                entry["error"] = exception.RuntimeErrorCode.ToString();
                report["status"] = "PLCSIM_INPUT_WRITE_FAILED";
                Program.AddError(report, signal.Name + ": WriteBit fallo (" + exception.RuntimeErrorCode + ").");
                return false;
            }
            if (!writtenInputs.Any(item => item.Name == signal.Name))
            {
                writtenInputs.Add(signal);
            }
            Thread.Sleep(settleMs);
            bool byAddress = instance.InputArea.ReadBit(signal.Offset, signal.Bit);
            bool byTag = instance.ReadBool(signal.Name);
            bool match = byAddress == value && byTag == value;
            entry["readback_address"] = byAddress;
            entry["readback_tag"] = byTag;
            entry["actual_readback"] = byAddress;
            entry["match"] = match;
            entry["readback_timestamp"] = DateTime.Now.ToString("o");
            if (!match)
            {
                report["status"] = "PLCSIM_INPUT_READBACK_MISMATCH";
                Program.AddError(report, signal.Name + ": se pidio " + value + " y se leyo " + byAddress + " (direccion) / " + byTag + " (tag).");
                return false;
            }
            return true;
        }

        /// <summary>
        /// Verificacion de cualquier senal de una secuencia: entradas/salidas fisicas (VerifySignal) o
        /// variables internas PROCESS_VARIABLE (VerifyProcessVariable).
        /// </summary>
        private static string VerifyAny(Dictionary<string, Program.TagMeta> tags, Program.SignalRequest signal, bool forWrite,
            string purpose, out string detail)
        {
            return signal.IsProcessVariable
                ? Program.VerifyProcessVariable(tags, signal, forWrite, purpose, out detail)
                : Program.VerifySignal(tags, signal, forWrite, out detail);
        }

        /// <summary>Evidencia: nombre logico del ensayo -> nombre Runtime realmente usado en PLCSIM.</summary>
        private static void RecordResolution(Dictionary<string, object> report, Program.SignalRequest signal)
        {
            if (!signal.IsProcessVariable)
            {
                return;
            }
            object existing;
            Dictionary<string, object> resolved = report.TryGetValue("resolved_process_variables", out existing) && existing is Dictionary<string, object>
                ? (Dictionary<string, object>)existing : new Dictionary<string, object>();
            resolved[signal.Name] = signal.ApiName;
            report["resolved_process_variables"] = resolved;
        }

        /// <summary>Lectura tipada: fisica por direccion (ReadBit); interna por nombre (ReadBool / ReadFloat).</summary>
        private static object ReadValue(IInstance instance, Program.SignalRequest signal)
        {
            if (signal.IsProcessVariable)
            {
                return signal.IsReal ? (object)(double)instance.ReadFloat(signal.ApiName) : instance.ReadBool(signal.ApiName);
            }
            IIOArea area = signal.Area == "Input" ? instance.InputArea : instance.OutputArea;
            return area.ReadBit(signal.Offset, signal.Bit);
        }

        /// <summary>Escritura interna tipada por nombre (WriteBool / WriteFloat). Nunca por direccion.</summary>
        private static void WriteVariable(IInstance instance, Program.SignalRequest signal, object value)
        {
            if (signal.IsReal)
            {
                instance.WriteFloat(signal.ApiName, (float)Convert.ToDouble(value));
            }
            else
            {
                instance.WriteBool(signal.ApiName, Convert.ToBoolean(value));
            }
        }

        /// <summary>
        /// op "set": escribe VARIAS senales (entradas fisicas con InputArea.WriteBit; variables internas
        /// escribibles por nombre), todas verificadas contra el programa cargado, y hace readback
        /// inmediato de todas (REAL con tolerancia). t_ms = reloj de la secuencia.
        /// </summary>
        private static bool SetMany(
            IInstance instance, Dictionary<string, Program.TagMeta> tags, Dictionary<string, object> step,
            Stopwatch clock, Dictionary<string, object> report, List<Program.SignalRequest> writtenInputs,
            Dictionary<string, KeyValuePair<Program.SignalRequest, object>> writtenVariables, string purpose, double realTolerance,
            int settleMs)
        {
            List<KeyValuePair<Program.SignalRequest, object>> writes = new List<KeyValuePair<Program.SignalRequest, object>>();
            foreach (object raw in AsList(step, "writes"))
            {
                Dictionary<string, object> item = raw as Dictionary<string, object> ?? new Dictionary<string, object>();
                Program.SignalRequest signal = Program.ParseSignal(item.ContainsKey("signal") ? item["signal"] : null);
                string detail;
                string error = VerifyAny(tags, signal, true, purpose, out detail);
                if (error != null)
                {
                    report["status"] = error;
                    Program.AddError(report, detail);
                    return false;
                }
                RecordResolution(report, signal);
                object requested = signal.IsProcessVariable && signal.IsReal
                    ? (object)GetDouble(item, "value", Double.NaN) : GetBool(item, "value");
                if (requested is double && Double.IsNaN((double)requested))
                {
                    report["status"] = "PLCSIM_SIGNAL_TYPE_UNSUPPORTED";
                    Program.AddError(report, signal.Name + ": valor REAL invalido en el paso " + Program.GetString(step, "id", "") + ".");
                    return false;
                }
                writes.Add(new KeyValuePair<Program.SignalRequest, object>(signal, requested));
            }
            double started = clock.Elapsed.TotalMilliseconds;
            string writeTimestamp = DateTime.Now.ToString("o");
            foreach (KeyValuePair<Program.SignalRequest, object> write in writes)
            {
                try
                {
                    if (write.Key.IsProcessVariable)
                    {
                        if (!writtenVariables.ContainsKey(write.Key.Name))
                        {
                            writtenVariables[write.Key.Name] = new KeyValuePair<Program.SignalRequest, object>(write.Key, ReadValue(instance, write.Key));
                        }
                        WriteVariable(instance, write.Key, write.Value);
                    }
                    else
                    {
                        instance.InputArea.WriteBit(write.Key.Offset, write.Key.Bit, (bool)write.Value);
                        if (!writtenInputs.Any(item => item.Name == write.Key.Name))
                        {
                            writtenInputs.Add(write.Key);
                        }
                    }
                }
                catch (SimulationRuntimeException exception)
                {
                    report["status"] = "PLCSIM_INPUT_WRITE_FAILED";
                    Program.AddError(report, write.Key.Name + ": escritura fallo (" + exception.RuntimeErrorCode + ").");
                    return false;
                }
            }
            double done = clock.Elapsed.TotalMilliseconds;
            List<object> entries = new List<object>();
            bool allMatch = true;
            foreach (KeyValuePair<Program.SignalRequest, object> write in writes)
            {
                if (write.Key.IsProcessVariable)
                {
                    // La llamada de escritura YA termino sin excepcion (write_call_success): la infraestructura
                    // escribio. Un readback distinto puede deberse a que el PROGRAMA bajo prueba reescribe la
                    // variable en su ciclo; eso no es infraestructura. Solo ante discrepancia se observa de nuevo
                    // tras io_settle_ms (el margen configurado para que corran ciclos del PLC) para separar un
                    // transitorio de una sobrescritura sostenida. Nunca falla la secuencia por esto.
                    object readback = ReadValue(instance, write.Key);
                    string readbackAt = DateTime.Now.ToString("o");
                    bool initialMatch = Program.ValueMatches(write.Value, readback, write.Key.IsReal, realTolerance);
                    Dictionary<string, object> entry = new Dictionary<string, object>
                    {
                        { "name", write.Key.Name }, { "runtime_name", write.Key.ApiName }, { "kind", Program.KindProcessVariable },
                        { "data_type", write.Key.DataType }, { "requested_value", write.Value }, { "write_call_success", true },
                        { "write_timestamp", writeTimestamp }, { "initial_readback", readback }, { "initial_readback_timestamp", readbackAt },
                        { "actual_readback", readback }, { "readback_tag", readback },
                        { "tolerance", write.Key.IsReal ? (object)realTolerance : null }, { "match", initialMatch },
                        { "classification", "CONFIRMED" }
                    };
                    if (!initialMatch)
                    {
                        Thread.Sleep(settleMs);
                        object observed = ReadValue(instance, write.Key);
                        bool observedMatch = Program.ValueMatches(write.Value, observed, write.Key.IsReal, realTolerance);
                        object original = writtenVariables[write.Key.Name].Value;
                        entry["observed_after_cycle"] = observed;
                        entry["observed_after_cycle_timestamp"] = DateTime.Now.ToString("o");
                        entry["observed_wait_ms"] = settleMs;
                        // Si lo observado es el valor previo a la escritura, no se puede distinguir con certeza
                        // entre "el programa lo restablece" y "la escritura no tuvo efecto": se registra.
                        entry["observed_equals_original"] = Program.ValueMatches(original, observed, write.Key.IsReal, realTolerance);
                        entry["classification"] = observedMatch ? "AMBIGUOUS_TRANSIENT" : "PROGRAM_OVERWRITES_HARNESS_INPUT";
                        entry["match"] = observedMatch;
                        if (!observedMatch)
                        {
                            List<object> overwrites = report.ContainsKey("harness_input_overwrites")
                                ? (List<object>)report["harness_input_overwrites"] : new List<object>();
                            overwrites.Add(new Dictionary<string, object>(entry) { { "step_id", Program.GetString(step, "id", "") } });
                            report["harness_input_overwrites"] = overwrites;
                        }
                    }
                    entries.Add(entry);
                    continue;
                }
                bool byAddress = instance.InputArea.ReadBit(write.Key.Offset, write.Key.Bit);
                bool byTag = instance.ReadBool(write.Key.Name);
                bool match = byAddress == (bool)write.Value && byTag == (bool)write.Value;
                allMatch &= match;
                entries.Add(new Dictionary<string, object>
                {
                    { "name", write.Key.Name }, { "address", write.Key.Address }, { "requested_value", write.Value },
                    { "actual_readback", byAddress }, { "readback_tag", byTag }, { "match", match }
                });
            }
            ((List<object>)report["events"]).Add(new Dictionary<string, object>
            {
                { "type", "set" }, { "id", Program.GetString(step, "id", "") }, { "phase", Program.GetString(step, "phase", "") },
                { "t_ms", started }, { "t_done_ms", done }, { "timestamp", DateTime.Now.ToString("o") }, { "writes", entries }
            });
            if (!allMatch)
            {
                report["status"] = "PLCSIM_INPUT_READBACK_MISMATCH";
                Program.AddError(report, "Readback de entradas no coincide en el paso " + Program.GetString(step, "id", "") + ".");
                return false;
            }
            return true;
        }

        /// <summary>
        /// op "sample": lee todas las senales cada period_ms durante duration_ms (siempre incluye
        /// una muestra final en >= duration_ms). `require` (opcional) se comprueba en la ultima
        /// muestra; si no se cumple, la secuencia se detiene (precondiciones del Oracle).
        /// </summary>
        private static bool Sample(
            IInstance instance, Dictionary<string, Program.TagMeta> tags, Dictionary<string, object> step,
            Stopwatch clock, Dictionary<string, object> report, string purpose)
        {
            List<Program.SignalRequest> signals = AsList(step, "signals").Select(Program.ParseSignal).ToList();
            foreach (Program.SignalRequest signal in signals)
            {
                string detail;
                string error = VerifyAny(tags, signal, false, purpose, out detail);
                if (error != null)
                {
                    report["status"] = error;
                    Program.AddError(report, detail);
                    return false;
                }
                RecordResolution(report, signal);
            }
            int duration = Math.Max(0, Math.Min(120000, GetInt(step, "duration_ms", 0)));
            int period = Math.Max(10, Math.Min(1000, GetInt(step, "period_ms", 50)));
            string id = Program.GetString(step, "id", "");
            string phase = Program.GetString(step, "phase", "");
            List<object> samples = (List<object>)report["samples"];
            double start = clock.Elapsed.TotalMilliseconds;
            Dictionary<string, object> last = null;
            int count = 0;
            while (true)
            {
                double now = clock.Elapsed.TotalMilliseconds;
                Dictionary<string, object> values = new Dictionary<string, object>();
                foreach (Program.SignalRequest signal in signals)
                {
                    values[signal.Name] = ReadValue(instance, signal);
                }
                last = values;
                samples.Add(new Dictionary<string, object> { { "id", id }, { "phase", phase }, { "t_ms", now }, { "values", values } });
                count++;
                if (now - start >= duration || count >= 20000)
                {
                    break;
                }
                double next = start + count * period;
                double remaining = Math.Min(next, start + duration) - clock.Elapsed.TotalMilliseconds;
                if (remaining > 0)
                {
                    Thread.Sleep((int)Math.Ceiling(remaining));
                }
            }
            object rawRequire;
            Dictionary<string, object> require = step.TryGetValue("require", out rawRequire) ? rawRequire as Dictionary<string, object> : null;
            if (require != null && last != null)
            {
                List<string> failed = new List<string>();
                foreach (KeyValuePair<string, object> expected in require)
                {
                    object actual;
                    if (!last.TryGetValue(expected.Key, out actual) || !Program.RequirementMatches(expected.Value, actual))
                    {
                        failed.Add(expected.Key + " esperado " + expected.Value + " observado " + (actual ?? "?"));
                    }
                }
                if (failed.Count > 0)
                {
                    report["status"] = "PLCSIM_SEQUENCE_REQUIREMENT_FAILED";
                    Program.AddError(report, "Requisito no cumplido en " + id + ": " + String.Join("; ", failed));
                    return false;
                }
            }
            return true;
        }

        private static bool ReadOne(
            IInstance instance, Dictionary<string, Program.TagMeta> tags, Program.SignalRequest signal,
            Dictionary<string, object> report, string label)
        {
            string detail;
            string error = Program.VerifySignal(tags, signal, false, out detail);
            if (error != null)
            {
                report["status"] = error;
                Program.AddError(report, detail);
                return false;
            }
            IIOArea area = signal.Area == "Input" ? instance.InputArea : instance.OutputArea;
            bool byAddress = area.ReadBit(signal.Offset, signal.Bit);
            bool byTag = instance.ReadBool(signal.Name);
            Dictionary<string, object> entry = new Dictionary<string, object>
            {
                { "label", label }, { "name", signal.Name }, { "address", signal.Address }, { "area", signal.Area },
                { "value", byAddress }, { "value_by_tag", byTag }, { "consistent", byAddress == byTag },
                { "source", "address" }, { "timestamp", DateTime.Now.ToString("o") }
            };
            ((List<object>)report["reads"]).Add(entry);
            ((List<object>)report["observations"]).Add(entry);
            if (byAddress != byTag)
            {
                report["status"] = signal.Area == "Input" ? "PLCSIM_INPUT_READBACK_MISMATCH" : "PLCSIM_OUTPUT_READ_FAILED";
                Program.AddError(report, signal.Name + ": direccion=" + byAddress + " y tag=" + byTag + " no coinciden.");
                return false;
            }
            return true;
        }

        private static void Cleanup(IInstance instance, List<Program.SignalRequest> inputs, int settleMs, Dictionary<string, object> report)
        {
            List<object> entries = new List<object>();
            bool allOk = true;
            foreach (Program.SignalRequest signal in inputs)
            {
                Dictionary<string, object> entry = new Dictionary<string, object> { { "name", signal.Name }, { "address", signal.Address } };
                try
                {
                    instance.InputArea.WriteBit(signal.Offset, signal.Bit, false);
                }
                catch (SimulationRuntimeException exception)
                {
                    entry["error"] = exception.RuntimeErrorCode.ToString();
                }
                entries.Add(entry);
            }
            Thread.Sleep(settleMs);
            foreach (Dictionary<string, object> entry in entries.Cast<Dictionary<string, object>>())
            {
                Program.SignalRequest signal = inputs.First(item => item.Name == (string)entry["name"]);
                bool value;
                bool ok;
                try
                {
                    value = instance.InputArea.ReadBit(signal.Offset, signal.Bit) || instance.ReadBool(signal.Name);
                    ok = !value && !entry.ContainsKey("error");
                    entry["readback"] = value;
                }
                catch (SimulationRuntimeException exception)
                {
                    entry["error"] = exception.RuntimeErrorCode.ToString();
                    ok = false;
                }
                entry["restored"] = ok;
                allOk &= ok;
            }
            report["cleanup"] = new Dictionary<string, object>
            {
                { "performed", true }, { "success", allOk }, { "inputs", entries }, { "timestamp", DateTime.Now.ToString("o") }
            };
            if (!allOk)
            {
                Program.AddError(report, "PLCSIM_IO_CLEANUP_FAILED: alguna entrada no volvio a FALSE.");
                if (GetString(report, "status") == "PLCSIM_IO_PASSED")
                {
                    report["status"] = "PLCSIM_IO_CLEANUP_FAILED";
                }
                report["cleanup_failed"] = true;
            }
        }

        /// <summary>
        /// discover_tags (SOLO LECTURA): lista los tags de DB del programa cargado (opcionalmente solo los de
        /// db_name) con el nombre Runtime REAL, area, tipo primitivo, offset/bit, indices y si la lectura
        /// tipada funciona. Sirve para comprobar el formato del nombre antes de usarlo (nunca se asume).
        /// </summary>
        private static void Discover(IInstance instance, List<STagInfo> infos, string dbName, Dictionary<string, object> report)
        {
            List<object> found = new List<object>();
            int total = 0;
            foreach (STagInfo tag in infos)
            {
                if (tag.Area.ToString() != "DataBlock")
                {
                    continue;
                }
                total++;
                if (!String.IsNullOrEmpty(dbName) && !tag.Name.StartsWith(dbName, StringComparison.Ordinal)
                    && !tag.Name.StartsWith("\"" + dbName + "\"", StringComparison.Ordinal))
                {
                    continue;
                }
                string primitive = tag.PrimitiveDataType.ToString();
                Dictionary<string, object> entry = new Dictionary<string, object>
                {
                    { "runtime_name", tag.Name }, { "area", tag.Area.ToString() }, { "primitive_type", primitive },
                    { "data_type", tag.DataType.ToString() }, { "size", (int)tag.Size }, { "offset", (long)tag.Offset },
                    { "bit", (int)tag.Bit }, { "index", (long)tag.Index }, { "parent_index", (long)tag.ParentIndex }
                };
                try
                {
                    if (primitive == "Bool")
                    {
                        entry["value"] = instance.ReadBool(tag.Name);
                        entry["readable"] = true;
                    }
                    else if (primitive == "Float")
                    {
                        entry["value"] = (double)instance.ReadFloat(tag.Name);
                        entry["readable"] = true;
                    }
                    else
                    {
                        entry["readable"] = null;  // tipo fuera de alcance (no se intenta leer)
                    }
                }
                catch (SimulationRuntimeException exception)
                {
                    entry["readable"] = false;
                    entry["read_error"] = exception.RuntimeErrorCode.ToString();
                }
                found.Add(entry);
                if (found.Count >= 500)
                {
                    break;
                }
            }
            report["db_name_filter"] = dbName;
            report["data_block_tags_total"] = total;
            report["data_block_tags"] = found;
            report["tag_list_is_hmi_visible_only"] = false;
        }

        /// <summary>
        /// Restauracion OBLIGATORIA de las variables internas escritas: el valor del cleanup del Oracle
        /// (restore_value) o, si no lo hay, el valor original leido antes de la primera escritura. Nunca
        /// BOOL->FALSE / REAL->0 por defecto. Se verifica por readback y queda como evidencia.
        /// </summary>
        private static void RestoreVariables(IInstance instance, Dictionary<string, KeyValuePair<Program.SignalRequest, object>> written,
            int settleMs, double realTolerance, Dictionary<string, object> report)
        {
            List<object> entries = new List<object>();
            bool allOk = true;
            foreach (KeyValuePair<string, KeyValuePair<Program.SignalRequest, object>> item in written)
            {
                Program.SignalRequest signal = item.Value.Key;
                object target = signal.HasRestore ? signal.RestoreValue : item.Value.Value;
                Dictionary<string, object> entry = new Dictionary<string, object>
                {
                    { "name", signal.Name }, { "runtime_name", signal.ApiName }, { "data_type", signal.DataType },
                    { "original_value", item.Value.Value },
                    { "restore_value", target }, { "restore_source", signal.HasRestore ? "ORACLE_CLEANUP" : "ORIGINAL_VALUE" }
                };
                try
                {
                    WriteVariable(instance, signal, target);
                }
                catch (SimulationRuntimeException exception)
                {
                    entry["error"] = exception.RuntimeErrorCode.ToString();
                }
                entries.Add(entry);
            }
            Thread.Sleep(settleMs);
            foreach (Dictionary<string, object> entry in entries.Cast<Dictionary<string, object>>())
            {
                Program.SignalRequest signal = written[(string)entry["name"]].Key;
                bool ok;
                try
                {
                    object readback = ReadValue(instance, signal);
                    entry["readback"] = readback;
                    ok = !entry.ContainsKey("error") && Program.ValueMatches(entry["restore_value"], readback, signal.IsReal, realTolerance);
                }
                catch (SimulationRuntimeException exception)
                {
                    entry["error"] = exception.RuntimeErrorCode.ToString();
                    ok = false;
                }
                entry["restored"] = ok;
                allOk &= ok;
            }
            object existing;
            Dictionary<string, object> cleanup = report.TryGetValue("cleanup", out existing) && existing is Dictionary<string, object>
                ? (Dictionary<string, object>)existing
                : new Dictionary<string, object> { { "performed", true }, { "success", true }, { "inputs", new List<object>() } };
            cleanup["process_variables"] = entries;
            cleanup["success"] = (bool)cleanup["success"] && allOk;
            cleanup["timestamp"] = DateTime.Now.ToString("o");
            report["cleanup"] = cleanup;
            if (!allOk)
            {
                Program.AddError(report, "PLCSIM_IO_CLEANUP_FAILED: alguna variable interna no volvio a su valor de restauracion.");
                if (GetString(report, "status") == "PLCSIM_IO_PASSED")
                {
                    report["status"] = "PLCSIM_IO_CLEANUP_FAILED";
                }
                report["cleanup_failed"] = true;
            }
        }

        private static double GetDouble(Dictionary<string, object> payload, string key, double fallback)
        {
            object value;
            if (payload.TryGetValue(key, out value) && value != null && !(value is bool))
            {
                try
                {
                    return Convert.ToDouble(value, System.Globalization.CultureInfo.InvariantCulture);
                }
                catch (FormatException)
                {
                    return fallback;
                }
            }
            return fallback;
        }

        private static Dictionary<string, object> Deny(Dictionary<string, object> report, string status, string message)
        {
            report["status"] = status;
            Program.AddError(report, message);
            Program.Log("I/O denied: " + message);
            return report;
        }

        private static List<object> AsList(Dictionary<string, object> payload, string key)
        {
            object value;
            if (payload.TryGetValue(key, out value) && value is System.Collections.IEnumerable && !(value is string))
            {
                return ((System.Collections.IEnumerable)value).Cast<object>().ToList();
            }
            return new List<object>();
        }

        private static bool GetBool(Dictionary<string, object> payload, string key)
        {
            object value;
            return payload.TryGetValue(key, out value) && value is bool && (bool)value;
        }

        private static int GetInt(Dictionary<string, object> payload, string key, int fallback)
        {
            object value;
            if (payload.TryGetValue(key, out value) && value != null)
            {
                try
                {
                    return Convert.ToInt32(value);
                }
                catch (FormatException)
                {
                    return fallback;
                }
            }
            return fallback;
        }

        private static string GetString(Dictionary<string, object> payload, string key)
        {
            return Program.GetString(payload, key, "");
        }
    }
}
