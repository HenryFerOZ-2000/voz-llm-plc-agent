"""Compile and execute the production word reader with scan-boundary I/O sequences."""
from pathlib import Path
import subprocess


def extract_method(source, signature):
    start=source.index(signature);opening=source.index('{',start);depth=1;end=opening+1
    while depth:
        if source[end]=='{':depth+=1
        elif source[end]=='}':depth-=1
        end+=1
    return source[start:end]


def test_output_change_between_api_reads_is_not_an_address_mismatch(project_root,tmp_path):
    source=(project_root/'plcsim_runtime_bridge/PidPlantSession.cs').read_text(encoding='utf-8')
    methods='\n'.join(extract_method(source,s) for s in ('private static int Decode(', 'private int ReadWord('))
    harness=r'''
using System;
using System.Threading;
class Program { internal class SignalRequest { public string Area="Output"; } }
class Probe {
    bool bigEndian=true,probePassed=true;
    int[] symbols,words;int si,wi;
    Probe(int[] symbols,int[] words){this.symbols=symbols;this.words=words;}
    object Read(Program.SignalRequest signal){return symbols[Math.Min(si++,symbols.Length-1)];}
    byte[] ReadWordBytes(Program.SignalRequest signal){int n=words[Math.Min(wi++,words.Length-1)];return new[]{(byte)(n>>8),(byte)n};}
    METHODS
    static int Main(){
        try {
            // QW changes on a PLC scan between the symbolic read and byte read.
            var changed=new Probe(new[]{1000,1001,1002,1002},new[]{1001,1002});
            if(changed.ReadWord(new Program.SignalRequest())!=1002)return 11;
            // The typed API can lag the process image for one observation.
            var delayed=new Probe(new[]{1000,1000,1001,1001},new[]{1001,1001});
            if(delayed.ReadWord(new Program.SignalRequest())!=1001)return 14;
            // A stable address/type disagreement must still fail closed.
            var wrong=new Probe(new[]{1000},new[]{2000});bool rejected=false;
            try{wrong.ReadWord(new Program.SignalRequest());}catch(InvalidOperationException){rejected=true;}
            if(!rejected)return 12;
            // Never accept a permanently changing observation or spin indefinitely.
            var unstable=new Probe(new[]{1,2,3,4,5,6,7,8,9,10,11,12},new[]{100});rejected=false;
            try{unstable.ReadWord(new Program.SignalRequest());}catch(InvalidOperationException){rejected=true;}
            if(!rejected || unstable.si>20)return 13;
            Console.WriteLine("scan-boundary, stable mismatch and bounded instability passed");return 0;
        } catch(Exception error){Console.WriteLine(error);return 1;}
    }
}
'''.replace('METHODS',methods)
    code=tmp_path/'WordProbe.cs';exe=tmp_path/'WordProbe.exe';code.write_text(harness,encoding='utf-8')
    compiler=Path('C:/Windows/Microsoft.NET/Framework64/v4.0.30319/csc.exe')
    built=subprocess.run([str(compiler),'/nologo','/out:'+str(exe),str(code)],capture_output=True,text=True,timeout=30)
    assert built.returncode==0,built.stdout+built.stderr
    result=subprocess.run([str(exe)],capture_output=True,text=True,timeout=5)
    assert result.returncode==0,result.stdout+result.stderr
