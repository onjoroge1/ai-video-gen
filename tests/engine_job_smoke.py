"""Real engine + real Postgres leases/finalization; local Blob double, no paid APIs."""
from pathlib import Path
import json
import os
import shutil
import subprocess
import sys
import tempfile
import uuid

# Running this file directly should resolve the actual checked-out application.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from durable_execution import PostgresStore, DurableRuntime, StorageUnavailable, file_sha256
from bolt_video.engines.jobs import EngineRequest, JOB_KIND, VERSION, queue, run_claimed


class LocalBlob:
    def __init__(self, root):
        self.root=Path(root);self.root.mkdir();self.objects={}
    def upload(self, path, remote):
        p=self.root/(uuid.uuid4().hex+Path(path).suffix);shutil.copy2(path,p)
        url='https://fixture.public.blob.vercel-storage.com/'+p.name
        self.objects[url]=p
        return dict(url=url,download_url=url,pathname=remote,sha256=file_sha256(p),
                    size_bytes=p.stat().st_size,access='private')
    def download(self, artifact, path):
        shutil.copy2(self.objects[artifact['url']],path);return path
    def delete(self,url):
        self.objects[url].unlink(missing_ok=True)


def main(engine):
    db_url=os.environ['TEST_DATABASE_URL']
    store=PostgresStore(db_url)
    root=Path(__file__).resolve().parents[1]
    evidence=root/'integrations/video_engines/runtime/reports/jobs'/engine
    evidence.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory() as directory:
        temp=Path(directory);blob=LocalBlob(temp/'blob');source=temp/'source.mp4'
        subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','testsrc2=s=540x960:r=24:d=4',
            '-f','lavfi','-i','sine=frequency=440:duration=4','-c:v','libx264','-pix_fmt','yuv420p',
            '-c:a','aac','-shortest',str(source)],check=True,timeout=30)
        srt=temp/'source.srt';srt.write_text('1\n00:00:00,000 --> 00:00:04,000\nLocal technical fixture.\n')
        source_id='source-'+uuid.uuid4().hex
        store.enqueue(job_id=source_id,kind='explainer',request={},max_cost_usd=0,
                      pipeline_version='fixture',output_prefix='fixtures')
        claimed=store.claim(job_id=source_id,worker_id='fixture')
        rt=DurableRuntime(source_id,'fixture',str(temp),store,blob)
        rt.finalize(str(source),{'title':'Local technical fixture','status':'done'}, {'srt':str(srt)})
        original=store.finished_get(source_id)
        data=dict(request_id=str(uuid.uuid4()),engine=engine,title='Connected engine '+engine,
                  source_video_id=source_id,source_rights_confirmed=True)
        if engine=='openshorts':data.update(start_sec=1,end_sec=3)
        if engine=='moneyprinterturbo':data['material_video_ids']=[source_id]
        if engine=='motion_canvas':
            data['storyboard']=dict(title='Before and after',flow='motion_scene',aspect_ratio='9:16',
                narration_script='A reward changes the choice.',shots=[dict(id='choice',start=0,end=4,
                narration='A reward changes the choice.',visual='Two choices and a moving token.',
                first_frame='Choice A',change='A reward appears beside B.',last_frame='Choice B',treatment='motion_canvas')])
        req=EngineRequest.model_validate(data)
        job=queue(req,store)
        assert store.claim(worker_id='explainer-must-ignore-engine') is None
        assert queue(req,store)['id']==job['id']
        # Force a storage failure after the render stage has been committed. The
        # next lease must restore the artifact, not execute the engine again.
        finalize=store.finalize_finished
        def fail_once(*args,**kwargs):raise StorageUnavailable('Injected finalization outage')
        store.finalize_finished=fail_once
        first=store.claim(job_id=job['id'],kind=JOB_KIND,worker_id='engine-first')
        result=run_claimed(first,store,blob)
        assert result['status']=='retry',result
        store.finalize_finished=finalize
        second=store.claim(job_id=job['id'],kind=JOB_KIND,worker_id='engine-second')
        def forbidden(*args):raise AssertionError('Completed engine render was called again')
        result=run_claimed(second,store,blob,renderer=forbidden)
        assert result['status']=='done',result
        finished=store.finished_get(job['id'])
        manifest=json.loads(blob.objects[finished['artifacts']['provenance']['url']].read_text())
        assert manifest['stage_reused'] and manifest['external_provider_calls']==0
        assert manifest['parent_video_id']==source_id
        assert finished['metadata']['actual_cost']==0
        assert store.finished_get(source_id)==original
        assert store.claim(job_id=job['id'],kind=JOB_KIND,worker_id='duplicate') is None
        blob.download(finished['artifacts']['video'],str(evidence/'result.mp4'))
        (evidence/'report.json').write_text(json.dumps({'engine':engine,'postgres_queue':True,
            'real_engine_render':True,'atomic_finalization':True,'cached_recovery':True,
            'source_unchanged':True,'provider_spend_usd':0,'blob_transport':'local_test_double',
            'technical':manifest['technical']},indent=2))
        print((evidence/'report.json').read_text())


if __name__=='__main__':main(sys.argv[1])
