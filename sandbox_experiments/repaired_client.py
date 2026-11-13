"""Credential-free mock provider boundary. Live collection is deliberately closed.

There is no networking or credential loading in this module. A future approved
live adapter must implement its own bounded protocol, wire ledger and pacing.
"""
import json
import hashlib

class LiveCollectionClosed(RuntimeError): pass

class RepairedResilientClient:
    model='mock-only'
    base_url=None
    def __init__(self,*args,**kwargs):
        raise LiveCollectionClosed('Live collection is closed. Use FixtureClient for labeled offline validation.')

class FixtureClient:
    model='offline-fixture-v1'
    base_url=None
    def __init__(self,policy,log_fn=None):
        self.policy=policy; self.log_fn=log_fn; self.request_ledger=[]
    def complete(self,messages,**settings):
        # Every call is visibly a mock; no attempt to infer provider tokens/cost.
        record=dict(kind='mock',index=len(self.request_ledger)+1,model=self.model,
                    messages=messages,settings=settings,usage=None)
        record['input_sha256']=hashlib.sha256(json.dumps(messages,sort_keys=True,allow_nan=False).encode()).hexdigest()
        try:
            raw=self.policy(messages)
            if not isinstance(raw,str): raise ValueError('fixture must return raw string')
            record.update(status='delivered',raw_response=raw)
        except Exception as exc:
            record.update(status='missing',error=type(exc).__name__+': '+str(exc))
            raise
        finally:
            self.request_ledger.append(record)
            if self.log_fn: self.log_fn(record)
        return raw
