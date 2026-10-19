using System;
using System.IO;
using System.Reflection;

// Execute the production lifetime helper using real files, without a TIA session.
class NativeSourceLifecycleProbe
{
    static int Main(string[] args)
    {
        string bridge=Path.GetFullPath(args[0]), folder=Path.GetFullPath(args[1]), scenario=args[2];
        AppDomain.CurrentDomain.AssemblyResolve+=(sender,e)=>{
            string name=new AssemblyName(e.Name).Name+".dll";
            string path=Path.Combine(Path.GetDirectoryName(bridge),name);
            return File.Exists(path)?Assembly.LoadFrom(path):null;
        };
        var type=Assembly.LoadFrom(bridge).GetType("VozLlmPlcAgent.TiaOpennessBridge.PidControlSupport");
        var method=type.GetMethod("GenerateTemporarySource",BindingFlags.Static|BindingFlags.NonPublic);
        if(method==null){Console.Error.WriteLine("Missing temporary-source lifecycle");return 1;}
        Directory.CreateDirectory(folder);
        string manual=Path.Combine(folder,"native_pid.scl");File.WriteAllText(manual,"manual source");
        string created=null;int generated=0,removed=0;bool failed=false;
        Func<string,FileInfo> create=name=>{
            created=Path.Combine(folder,name);
            if(scenario=="create_failure")throw new IOException("create failed");
            using(var stream=new FileStream(created,FileMode.CreateNew)){stream.WriteByte(42);}
            return new FileInfo(created);
        };
        Action<FileInfo> generate=source=>{
            if(!source.Exists)throw new Exception("missing generated source");
            generated++;
            if(scenario=="generate_failure")throw new IOException("generate failed");
            File.WriteAllText(Path.Combine(folder,"generated_block"),"compiled control");
        };
        Action<FileInfo> remove=source=>{
            if(scenario=="delete_failure")throw new IOException("delete failed");
            source.Delete();removed++;
        };
        try{method.MakeGenericMethod(typeof(FileInfo)).Invoke(null,new object[]{create,generate,remove});}
        catch(TargetInvocationException e){failed=e.InnerException is IOException;}
        bool ok=File.ReadAllText(manual)=="manual source" && created!=manual;
        if(scenario=="success")ok &= !failed && generated==1 && removed==1 && !File.Exists(created) && File.Exists(Path.Combine(folder,"generated_block"));
        if(scenario=="generate_failure")ok &= failed && generated==1 && removed==1 && !File.Exists(created);
        if(scenario=="create_failure")ok &= failed && generated==0 && removed==0;
        if(scenario=="delete_failure")ok &= failed && generated==1 && removed==0;
        Console.WriteLine(ok?"PASSED":"FAILED");return ok?0:1;
    }
}
