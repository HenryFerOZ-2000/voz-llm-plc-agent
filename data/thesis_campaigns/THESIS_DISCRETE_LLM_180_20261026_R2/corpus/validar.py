"""Verify the distributed paired WAV corpus locally, without service calls."""
from pathlib import Path
import array
import hashlib
import json
import math
import wave

BASE=Path(__file__).resolve().parent.parent
index=json.loads((BASE/'corpus/index.json').read_text(encoding='utf-8'))
manifests=json.loads((BASE/'manifiestos_audio_60.json').read_text(encoding='utf-8'))
assert len(index['entries'])==60
assert len({(e['case_id'],e['variant_id']) for e in index['entries']})==60
seen=set();snrs=[]
for entry in index['entries']:
    signals={}
    for condition in ['clean','noise']:
        item=entry[condition];path=(BASE/item['path']).resolve()
        assert path.is_relative_to(BASE.resolve())
        assert item['path'] not in seen
        seen.add(item['path'])
        assert hashlib.sha256(path.read_bytes()).hexdigest()==item['sha256'],item['path']
        with wave.open(str(path),'rb') as stream:
            assert (stream.getnchannels(),stream.getsampwidth(),stream.getframerate())==(1,2,16000)
            assert stream.getnframes()==item['frames']
            signals[condition]=array.array('h',stream.readframes(stream.getnframes()))
        asr=json.loads((BASE/item['asr_record']).read_text(encoding='utf-8'))
        assert asr['audio_hash']==item['sha256']
    assert len(signals['clean'])==len(signals['noise'])
    manifest=next(m for m in manifests if m['case_id']==entry['case_id'] and m['variant']==entry['variant_id'])
    assert manifest['clean_sha256']==entry['clean']['sha256']
    assert manifest['noisy_sha256']==entry['noise']['sha256']
    start,stop=manifest['active_region_samples'];gain=manifest['post_mix_gain']
    x,y=signals['clean'][start:stop],signals['noise'][start:stop]
    speech=sum((gain*v)**2 for v in x)
    noise=sum((v-gain*u)**2 for u,v in zip(x,y))
    snr=10*math.log10(speech/noise)
    assert 9.75<=snr<=10.25
    assert max(abs(v) for v in signals['noise'])<32767
    snrs.append(snr)
assert len(seen)==120
assert len(list((BASE/'corpus').rglob('*.wav')))==120
print(json.dumps({'status':'VERIFIED','WAV_files':120,'paired_utterances':60,
                  'format':'PCM16 mono 16000 Hz','SNR_min_db':min(snrs),
                  'SNR_max_db':max(snrs)},indent=2))
