using System;
using System.Collections.Generic;
using System.Linq;
using System.Net;

namespace VozLlmPlcAgent.TiaOpennessBridge
{
    internal static class ConnectionTargetSupport
    {
        static string Text(Dictionary<string,object> values,string key)
        {object value;return values.TryGetValue(key,out value)?Convert.ToString(value).Trim():"";}

        internal static Dictionary<string,object> SelectInterface(IEnumerable<Dictionary<string,object>> candidates,Dictionary<string,object> request)
        {
            string mode=Text(request,"configuration_mode"),name=Text(request,"pc_interface"),number=Text(request,"pc_interface_number");
            var matches=candidates.Where(c=>(mode=="" || String.Equals(Text(c,"mode"),mode,StringComparison.OrdinalIgnoreCase))
                && (name!=""?String.Equals(Text(c,"pc_interface"),name,StringComparison.OrdinalIgnoreCase):
                    Text(request,"target_type")!="PLCSIM_ADVANCED" || Text(c,"pc_interface").IndexOf("PLCSIM",StringComparison.OrdinalIgnoreCase)>=0)
                && (number=="" || Text(c,"number")==number)).ToList();
            if(matches.Count!=1)throw new InvalidOperationException("TIA_DOWNLOAD_AMBIGUOUS_TARGET: seleccione una interfaz PG/PC y su numero.");
            return matches[0];
        }

        internal static string ValidateAddress(Dictionary<string,object> request)
        {
            string text=Text(request,"target_address");if(text=="")return null;
            string[] parts=text.Split('.');byte value;
            if(parts.Length!=4 || parts.Any(p=>!Byte.TryParse(p,out value) || p!=value.ToString()))
                throw new InvalidOperationException("TARGET_ADDRESS_INVALID: se necesita una IPv4 unicast.");
            var ip=IPAddress.Parse(text);var bytes=ip.GetAddressBytes();
            if(bytes[0]==0 || bytes[0]==127 || bytes[0]>=224)
                throw new InvalidOperationException("TARGET_ADDRESS_INVALID: se necesita una IPv4 unicast.");
            return ip.ToString();
        }
    }
}
