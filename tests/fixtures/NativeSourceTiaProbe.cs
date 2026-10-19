using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Web.Script.Serialization;
using Siemens.Engineering;
using Siemens.Engineering.Compiler;
using Siemens.Engineering.SW;

// Explicit live probe, never run by pytest. Uses the real product import paths.
class NativeSourceTiaProbe
{
    static JavaScriptSerializer json=new JavaScriptSerializer();
    static Type program;
    static object Call(string name,params object[] args)
    {
        try{return program.GetMethod(name,BindingFlags.NonPublic|BindingFlags.Static).Invoke(null,args);}
        catch(TargetInvocationException e){throw e.InnerException;}
    }
    static void Save(string path,object value){File.WriteAllText(path,json.Serialize(value));}
    static int Main(string[] args)
    {
        AppDomain.CurrentDomain.AssemblyResolve+=(sender,e)=>{
            string name=new AssemblyName(e.Name).Name+".dll";
            foreach(string dir in new[]{Path.GetDirectoryName(args[0]),@"C:\Program Files\Siemens\Automation\Portal V18\PublicAPI\V18",@"C:\Program Files\Siemens\Automation\Portal V18\Bin\PublicAPI",@"C:\Program Files\Siemens\Automation\Portal V18\Bin"})
            {string path=Path.Combine(dir,name);if(File.Exists(path))return Assembly.LoadFrom(path);}
            return null;
        };
        try{return Run(args);}
        catch(Exception e){Console.Error.WriteLine(e.ToString());return 1;}
    }
    static int Run(string[] args)
    {
        program=Assembly.LoadFrom(args[0]).GetType("VozLlmPlcAgent.TiaOpennessBridge.Program");
        var request=json.Deserialize<Dictionary<string,object>>(File.ReadAllText(args[1]));
        string action=Convert.ToString(request["action"]),result=Convert.ToString(request["result_path"]);
        if(action=="snapshot")
        {
            var report=(Dictionary<string,object>)Call("NewReport","RUNNING");
            Console.WriteLine("SNAPSHOT: connecting to saved Normal project");
            string status=(string)Call("ArchiveNativePidSource",request,Convert.ToString(request["directory"]),report);
            report["status"]=status;Save(result,report);Console.WriteLine(status);return status=="CREATED"?0:1;
        }
        if(action=="import_compile" || action=="native_pid_import_compile")
        {
            var report=(Dictionary<string,object>)Call(action=="import_compile"?"ExecuteImportAndCompile":"ExecuteNativePidCompile",request);
            Save(result,report);Console.WriteLine(report["status"]);return Convert.ToString(report["status"])=="TIA_COMPILATION_PASSED"?0:1;
        }
        using(var portal=new TiaPortal(TiaPortalMode.WithoutUserInterface))
        {
            if(action=="retrieve")
            {
                var project=portal.Projects.Retrieve(new FileInfo(Convert.ToString(request["archive_path"])),new DirectoryInfo(Convert.ToString(request["directory"])));
                Save(result,new Dictionary<string,object>{{"project_path",project.Path.FullName}});project.Close();return 0;
            }
            var p=portal.Projects.Open(new FileInfo(Convert.ToString(request["project_path"])));
            try
            {
                var plc=(PlcSoftware)Call("FindPlcSoftware",p,"");
                if(action=="seed_manual")
                {
                    string file=Convert.ToString(request["source_path"]);
                    foreach(string name in new[]{"native_pid.scl","Manual_User.scl"})
                        if(plc.ExternalSourceGroup.ExternalSources.Find(name)==null)plc.ExternalSourceGroup.ExternalSources.CreateFromFile(name,file);
                    p.Save();
                }
                var report=(Dictionary<string,object>)Call("DescribePlcProject",p,"");
                var compiled=plc.GetService<ICompilable>().Compile();report["error_count"]=compiled.ErrorCount;
                Save(result,report);return compiled.ErrorCount==0?0:1;
            }
            finally{p.Close();}
        }
    }
}
