# 12 Integracion Voz

## Objetivo

Agregar una entrada de voz que apoye la usabilidad sin romper el control humano ni la seguridad del proceso.

## Flujo

1. El usuario inicia la grabacion.
2. El usuario detiene la grabacion.
3. Se genera un WAV temporal.
4. La GUI transcribe en segundo plano mediante el modelo ASR configurado.
5. La transcripcion aparece en el campo del comando y puede editarse.
6. Solo despues de la revision humana se procesa el comando.
7. La generacion del paquete PLC permanece como una accion separada.

## Uso desde la interfaz

1. (Opcional) Elegir un microfono en el selector "Microfono predeterminado del sistema" y usar `Actualizar microfonos` si se conecto un dispositivo nuevo.
2. Presionar `Escuchar comando` y dictar la orden industrial; el medidor de nivel y el tiempo transcurrido confirman que el microfono esta captando audio.
3. Presionar `Detener y transcribir` (o esperar el corte automatico al llegar al tope de duracion).
4. Revisar o corregir el texto reconocido.
5. Presionar `Procesar comando` para obtener la salida semantica.
6. Presionar `Generar paquete PLC` cuando la interpretacion sea correcta.

## Modulo

`src/speech_recognizer.py`

## Alcance actual

- deteccion del dispositivo de entrada y captura local en WAV mono de 16 kHz;
- selector de microfono en la GUI (`src/gui.py`) sobre `SpeechRecognizer.list_input_devices()`/`set_input_device()`, para elegir entre varios dispositivos de audio en vez de depender siempre del predeterminado del sistema;
- tope de duracion de grabacion (`max_recording_seconds`, 60 s por defecto) aplicado dentro del propio callback de audio mediante `sd.CallbackStop()`: si el usuario olvida presionar "Detener", la grabacion se corta sola en vez de crecer sin limite en memoria;
- medidor de nivel en vivo (peak/RMS) durante la grabacion, calculado por bloque en `SpeechRecognizer._update_level` y mostrado en la GUI junto con el tiempo transcurrido;
- deteccion local de silencio antes de llamar a la API: si el RMS de la grabacion cae bajo `silence_rms_threshold` (150 por defecto), se rechaza localmente sin gastar una llamada paga a transcripcion;
- timeout explicito y un reintento automatico ante fallas transitorias de red (`APITimeoutError`/`APIConnectionError`) en la llamada de transcripcion, con `retries_used` reportado en el resultado;
- transcripcion en espanol con contexto de vocabulario industrial;
- procesamiento en segundo plano para mantener la GUI operativa;
- estados de botones que evitan grabaciones o transcripciones duplicadas;
- conservacion de evidencia solo si el usuario la activa;
- reproduccion local en Windows cuando es viable;
- revision humana obligatoria antes de interpretar y generar codigo.

## Configuracion (`config/llm_config.json`)

- `max_recording_seconds`: tope de seguridad de duracion de grabacion.
- `silence_rms_threshold`: nivel RMS minimo (escala int16) para considerar que hay audio util.
- `transcription_timeout_seconds` / `transcription_max_retries`: timeout y reintentos de la llamada de transcripcion.

## Validacion realizada

Se valido el flujo con audio sintetico en espanol. La frase `Haz que el motor se encienda con Start y se apague con Stop` fue transcrita y clasificada como `INT_MOTOR_START_STOP`, sin aclaraciones y con salida semantica valida.

`tests/test_voice_module.py` cubre ademas: rechazo local de grabaciones silenciosas sin llamar a la API, reintento automatico ante un timeout transitorio seguido de exito, agotamiento de reintentos, seguimiento del nivel de audio en vivo y listado/seleccion de dispositivos de entrada (con `sounddevice` simulado, sin depender de hardware real).

## Limitaciones

- depende de microfono disponible;
- requiere API y modelo de transcripcion configurados para ASR;
- no procesa ruido de forma avanzada mas alla del rechazo de silencio por RMS.
