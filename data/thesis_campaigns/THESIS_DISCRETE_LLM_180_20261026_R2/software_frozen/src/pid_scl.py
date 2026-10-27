"""Native Siemens PID generation. No Python substitute for PID_Compact."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
from xml.etree import ElementTree as ET

from analog_scaling import real_literal
from plc_ir import PLCVariable
from utils import get_project_root
from process_signals import process_db_descriptors

OWNER='VozLlmPlcAgent.NativePID.v2'


def pid_implementation_identity():
    root=get_project_root()
    files=('src/pid_scl.py','src/code_generator.py','src/analog_scaling.py','src/platforms/siemens_scl_adapter.py',
           'src/process_signals.py','config/native_pid_map_defaults.json','config/native_pid_cyclic_ob.xml')
    return hashlib.sha256(b''.join((root/p).read_bytes().replace(b'\r\n',b'\n') for p in files)).hexdigest()


def prepare_pid_variables(project, io_index):
    loop=project.pid_loops[0]
    identity={'implementation':pid_implementation_identity(),'loop':loop.to_dict(),'devices':[(v.name,v.location,v.data_type) for v in project.pou.variables]}
    digest=hashlib.sha256(json.dumps(identity,sort_keys=True,allow_nan=False).encode()).digest()
    signature=[int.from_bytes(digest[i:i+2],'big',signed=True) for i in range(0,32,2)]
    project.metadata['pid_build_signature']=signature
    fields={
        'CmdStart':('BOOL','FALSE'),'CmdStop':('BOOL','FALSE'),'CmdReset':('BOOL','FALSE'),
        'CmdManual':('BOOL','FALSE'),'CmdPretune':('BOOL','FALSE'),'CmdFinetune':('BOOL','FALSE'),
        'ParametersConfirmed':('BOOL','FALSE'),
        'SP':('REAL',real_literal(loop.setpoint)),'ManualValue':('REAL','0.0'),
        'PV':('REAL','0.0'),'CV':('REAL','0.0'),'Running':('BOOL','FALSE'),'Fault':('BOOL','FALSE'),
        'Kp':('REAL','0.0'),'Ti':('REAL','0.0'),'Td':('REAL','0.0'),
        'SensorValid':('BOOL','FALSE'),'ControllerError':('BOOL','FALSE'),'ErrorBits':('DWORD','0'),
        'CurrentErrorBits':('DWORD','0'),'FaultCode':('INT','0'),
        'ControllerState':('INT','0'),'RequestedMode':('INT','0'),'PreviousMode':('INT','-1'),
        'ModePulse':('BOOL','FALSE'),'StartSignal':('BOOL','FALSE'),'StopSignal':('BOOL','FALSE'),
        'ResetSignal':('BOOL','FALSE'),'EmergencySignal':('BOOL','FALSE'),'StartPulse':('BOOL','FALSE'),
        'PreviousStart':('BOOL','FALSE'),'Initialized':('BOOL','FALSE'),'FaultCause':('BOOL','FALSE'),
        'PreviousPretune':('BOOL','FALSE'),'PreviousFinetune':('BOOL','FALSE'),
        'TuningMode':('INT','0'),'PreviousControllerState':('INT','0'),
    }
    fields.update({f'Build{i:02d}':('INT',str(value)) for i,value in enumerate(signature)})
    if {n.casefold() for n in fields}&{n.casefold() for n in io_index}:
        raise ValueError('PID_SYMBOL_CONFLICT: un nombre interno del lazo coincide con el mapa.')
    bindings=[]
    for connection in (loop.input_binding, loop.output_binding):
        if connection['representation'] != 'HARDWARE_RAW':
            continue
        name = connection['name']
        binding = dict(name=name, direction='input' if connection['role']=='MEASUREMENT' else 'output',
                       location=connection['address'], engineering_variable=f'M_{name}_EU',
                       valid_variable=f'M_{name}_Valid', raw_variable=f'M_{name}_RawCommand',
                       config=connection['analog_config'])
        for key, typ in [('engineering_variable','REAL'),('valid_variable','BOOL')] + (
                [('raw_variable','REAL')] if binding['direction']=='output' else []):
            field=binding[key]
            if field.casefold() in {n.casefold() for n in (*fields,*io_index)} or len(field)>100:
                raise ValueError(f'PID_SYMBOL_CONFLICT: {field}: auxiliar de escala ocupado o demasiado largo.')
            fields[field]=(typ,'FALSE' if typ=='BOOL' else '0.0')
        bindings.append(binding)
    project.metadata['analog_bindings']=bindings
    generated_internal=[]
    for name,(typ,initial) in fields.items():
        variable=PLCVariable(name,typ,'internal',None,initial,'PID interno','generated_pid',False)
        project.pou.variables.append(variable)
        generated_internal.append(variable.to_dict())
    project.metadata['authorized_variables']+=list(fields)
    project.metadata['generated_internal_variables']+=generated_internal
    project.metadata['authorized_variables']+=list(project.metadata['pid_db_access'])


def render_pid_body(loop):
    r=loop.resources
    signal=lambda role,internal:r.get(role,internal)
    low,high=(real_literal(loop.input_binding[k]) for k in ('engineering_min','engineering_max'))
    lines=['(* PID_OWNER_BINDING *)','(* Control nativo PID_Compact conectado al mapa IO. *)',
        f'StartSignal := {signal("start","CmdStart")} OR CmdStart;',
        f'StopSignal := {signal("stop","CmdStop")} OR CmdStop;',
        f'ResetSignal := {signal("reset","CmdReset")} OR CmdReset;',
        f'EmergencySignal := {signal("emergency","FALSE")};',
        'StartPulse := Initialized AND StartSignal AND NOT PreviousStart;']
    if loop.start_policy=='CONTINUOUS_EXPLICIT': lines+=['StartPulse := StartPulse OR NOT Initialized;']
    lines+=['PreviousStart := StartSignal;']
    if loop.input_binding['representation']=='HARDWARE_RAW':
        lines +=[f'PV := {loop.process_input};',f'SensorValid := M_{loop.process_input}_Valid;']
    else:
        lines +=[f'PV := {loop.process_input};',
                 f'SensorValid := {loop.process_input}_Quality AND (PV >= {low}) AND (PV <= {high});']
    causes=[('EmergencySignal',1),('NOT SensorValid',2),(f'NOT ((SP >= {low}) AND (SP <= {high}))',3)]
    if 'auto' in r:
        causes.append((f'({r["auto"]} AND ({signal("manual","CmdManual")} OR CmdManual))',4))
    if loop.overfill_limit is not None: causes.append((f'(PV >= {real_literal(loop.overfill_limit)})',5))
    causes.append(('ControllerError',6))
    lines +=['FaultCause := '+' OR '.join(c for c,_ in causes)+';','IF FaultCause THEN','    IF NOT Fault THEN']
    for i,(condition,code) in enumerate(causes):
        lines +=[('        IF ' if i==0 else '        ELSIF ')+condition+' THEN',f'            FaultCode := {code};']
    lines +=['        END_IF;','    END_IF;','    IF EmergencySignal THEN','        FaultCode := 1;','    END_IF;',
        '    Fault := TRUE;','    Running := FALSE;',
        'ELSIF Fault THEN','    Running := FALSE;','    IF ResetSignal AND NOT StartPulse THEN','        Fault := FALSE;',
        '        FaultCode := 0;','        ErrorBits := 0;','    END_IF;',
        'ELSIF StopSignal THEN','    Running := FALSE;',
        'ELSIF StartPulse THEN','    Running := TRUE;','END_IF;',
        'IF NOT Running OR Fault OR StopSignal THEN','    RequestedMode := 0;','    TuningMode := 0;',
        'ELSE','    IF CmdPretune AND NOT PreviousPretune THEN','        TuningMode := 1;',
        '    ELSIF CmdFinetune AND NOT PreviousFinetune THEN','        TuningMode := 2;','    END_IF;',
        f'    IF {signal("manual","CmdManual")} OR CmdManual THEN','        RequestedMode := 4;',
        '        TuningMode := 0;',
        '    ELSIF TuningMode > 0 THEN','        RequestedMode := TuningMode;',
        '    ELSIF ParametersConfirmed THEN','        RequestedMode := 3;','    ELSE','        RequestedMode := 4;','    END_IF;',
        'END_IF;']
    if 'auto' in r:
        lines +=[f'IF NOT {r["auto"]} AND NOT ({signal("manual","CmdManual")} OR CmdManual) THEN',
                 '    Running := FALSE;','    RequestedMode := 0;','    TuningMode := 0;','END_IF;']
    lines +=['ModePulse := RequestedMode <> PreviousMode;','PreviousControllerState := ControllerState;',
        '(* NATIVE_PID_BEGIN *)',
        f'"{loop.symbols["controller"]}"(Setpoint := SP, Input := PV,',
        '    ManualEnable := FALSE, ManualValue := ManualValue,',
        '    Reset := NOT Running OR Fault OR StopSignal, ErrorAck := ResetSignal,',
        '    Mode := RequestedMode, ModeActivate := ModePulse,',
        '    Output => CV, State => ControllerState, Error => ControllerError, ErrorBits => CurrentErrorBits);',
        f'Kp := "{loop.symbols["controller"]}".Retain.CtrlParams.Gain;',
        f'Ti := "{loop.symbols["controller"]}".Retain.CtrlParams.Ti;',
        f'Td := "{loop.symbols["controller"]}".Retain.CtrlParams.Td;',
        '(* NATIVE_PID_END *)',
        'IF (ControllerState = 3) AND ((PreviousControllerState = 1) OR (PreviousControllerState = 2)) AND NOT ControllerError THEN',
        '    TuningMode := 0;','    ParametersConfirmed := TRUE;','END_IF;',
        'IF ControllerError THEN','    IF NOT Fault THEN','        FaultCode := 6;','    END_IF;',
        '    Fault := TRUE;','    ErrorBits := CurrentErrorBits;',
        '    Running := FALSE;','    TuningMode := 0;','END_IF;',
        'IF NOT Running OR Fault THEN',f'    CV := {real_literal(loop.output_binding.get("analog_config",loop.output_binding)["fault_value"])};','END_IF;',
        'IF NOT ((CV >= 0.0) AND (CV <= 100.0)) THEN','    CV := 0.0;','    Fault := TRUE;','    FaultCode := 7;','    Running := FALSE;','END_IF;']
    if loop.control_output:
        lines +=[f'{loop.control_output} := CV;']
    for key in ('enable_output','alarm_output'):
        if key in r: lines +=[f'{r[key]} := '+('Running AND NOT Fault;' if key=='enable_output' else 'Fault;')]
    lines+=['PreviousMode := RequestedMode;',
        'PreviousPretune := CmdPretune;','PreviousFinetune := CmdFinetune;','Initialized := TRUE;']
    return '\n'.join(lines)+'\n'


def build_pid_infrastructure(project):
    loops=[]
    for loop in project.pid_loops:
        config={'implementation':pid_implementation_identity(),'loop':loop.to_dict()}
        fingerprint=hashlib.sha256(json.dumps(config,sort_keys=True,allow_nan=False).encode()).hexdigest()
        loops.append({**loop.to_dict(),'technology_version':loop.controller['technology_version'],
                      'configuration_hash':fingerprint,'ob_number':30})
    return {'schema_version':2,'owner':OWNER,'loops':loops,'process_dbs':_process_dbs(project), 'cyclic_ob_file':'pid_cyclic_ob.xml',
            'native_execution_status':'PENDING','physical_download_allowed':False}


def _process_dbs(project):
    return process_db_descriptors([binding for loop in project.pid_loops
        for binding in (loop.input_binding,loop.output_binding)],OWNER)


def render_pid_source(project,adapter):
    loop=project.pid_loops[0]
    db_sources=[]
    for group in _process_dbs(project):
        db_sources += [f'DATA_BLOCK "{group["db"]}"',"{ S7_Optimized_Access := 'TRUE' }",'VERSION : 0.1',
                       'NON_RETAIN','VAR']
        for member in group['members']:
            value='FALSE' if member['data_type']=='BOOL' else real_literal(member['initial'])
            db_sources += [f'    {member["name"]} : {member["data_type"]} := {value};']
        db_sources += ['END_VAR','BEGIN','END_DATA_BLOCK','']
    return '\n'.join(db_sources+['// Generated native PID; invoked exclusively by cyclic interrupt OB.',
        f'FUNCTION_BLOCK "{loop.symbols["fb"]}"',"{ S7_Optimized_Access := 'TRUE' }",'VERSION : 0.1',
        adapter.render_declarations(project).rstrip(),'BEGIN',adapter.render_implementation(project).rstrip(),'END_FUNCTION_BLOCK','',
        f'DATA_BLOCK "{loop.symbols["db"]}"',"{ S7_Optimized_Access := 'TRUE' }",'VERSION : 0.1','NON_RETAIN',
        f'"{loop.symbols["fb"]}"','BEGIN','END_DATA_BLOCK',''])


def render_pid_cyclic_ob(project,capabilities):
    if capabilities.get('secondary_type')!='CyclicInterrupt' or capabilities.get('cyclic_time_us')!=100000:
        raise ValueError('PID_CYCLIC_OB_UNVERIFIED: falta contrato V18 comprobado.')
    loop=project.pid_loops[0]
    if loop.period_ms!=100:
        raise ValueError('PID_CYCLIC_OB_UNVERIFIED: solo se ha comprobado el periodo de 100 ms.')
    root=ET.parse(get_project_root()/'config/native_pid_cyclic_ob.xml').getroot()
    attrs=root.find('SW.Blocks.OB/AttributeList')
    attrs.find('Name').text=loop.symbols['ob']
    attrs.find('AutoNumber').text='false'
    attrs.find('Number').text='30'
    ns='http://www.siemens.com/automation/Openness/SW/NetworkSource/StructuredText/v3'
    ET.register_namespace('st',ns)
    interface_ns='http://www.siemens.com/automation/Openness/SW/Interface/v5'
    ET.register_namespace('ifc',interface_ns)
    st=root.find('.//{'+ns+'}StructuredText'); st.clear()
    uid=20
    def sub(parent,tag,**attrs):
        nonlocal uid
        uid+=1
        return ET.SubElement(parent,'{'+ns+'}'+tag,{**attrs,'UId':str(uid)})
    call=sub(sub(st,'Access',Scope='Call'),'CallInfo',BlockType='FB',Name=loop.symbols['fb'])
    component=sub(sub(call,'Instance',Scope='GlobalVariable'),'Component',Name=loop.symbols['db'])
    sub(component,'BooleanAttribute',Name='HasQuotes').text='true'
    sub(call,'Token',Text='(')
    externals=[v for v in project.pou.variables if v.var_class in {'input','output'}]
    for i,v in enumerate(externals):
        if i: sub(call,'Token',Text=',')
        param=sub(call,'Parameter',Name=v.name)
        sub(param,'Token',Text=':=' if v.var_class=='input' else '=>')
        sym=sub(sub(param,'Access',Scope='GlobalVariable'),'Symbol')
        storage=project.metadata['pid_db_access'].get(v.name)
        if storage:
            sub(sub(sym,'Component',Name=storage['db']),'BooleanAttribute',Name='HasQuotes').text='true'
            sub(sym,'Token',Text='.')
            sub(sym,'Component',Name=storage['member'])
        else:
            sub(sub(sym,'Component',Name=v.name),'BooleanAttribute',Name='HasQuotes').text='true'
    sub(call,'Token',Text=')');sub(st,'Token',Text=';');sub(st,'NewLine',Num='1')
    xml=ET.tostring(root,encoding='unicode',xml_declaration=True)
    # V18's SimaticML importer requires local default namespaces for these embedded schemas.
    xml=xml.replace('<ifc:Sections',f'<Sections xmlns="{interface_ns}"').replace('ifc:','')
    xml=xml.replace('<st:StructuredText',f'<StructuredText xmlns="{ns}"').replace('st:','')
    return xml
