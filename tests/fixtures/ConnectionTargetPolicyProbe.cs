using System;
using System.Collections.Generic;
using VozLlmPlcAgent.TiaOpennessBridge;
class ConnectionTargetPolicyProbe
{
    static int Main()
    {
        var choices=new[]{
            new Dictionary<string,object>{{"mode","PN/IE"},{"pc_interface","Ethernet"},{"number",1}},
            new Dictionary<string,object>{{"mode","PN/IE"},{"pc_interface","Ethernet"},{"number",2}}};
        var request=new Dictionary<string,object>{{"configuration_mode","PN/IE"},{"pc_interface","Ethernet"},{"target_type","PHYSICAL_PLC"}};
        bool ambiguous=false;try{ConnectionTargetSupport.SelectInterface(choices,request);}catch(InvalidOperationException){ambiguous=true;}
        if(!ambiguous)return 1;
        request["pc_interface_number"]=2;
        if(Convert.ToInt32(ConnectionTargetSupport.SelectInterface(choices,request)["number"])!=2)return 2;
        if(ConnectionTargetSupport.ValidateAddress(request)!=null)return 3;
        request["target_address"]="192.168.0.2";
        if(ConnectionTargetSupport.ValidateAddress(request)!="192.168.0.2")return 4;
        foreach(string address in new[]{"999.1.1.1","127.0.0.1","0.0.0.0","224.0.0.1","255.255.255.255"})
        {
            request["target_address"]=address;bool rejected=false;
            try{ConnectionTargetSupport.ValidateAddress(request);}catch(InvalidOperationException){rejected=true;}
            if(!rejected)return 5;
        }
        Console.WriteLine("PASSED");return 0;
    }
}
