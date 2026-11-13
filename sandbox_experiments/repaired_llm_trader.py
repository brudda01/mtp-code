"""Strict decisions and explicit prompt inputs for sandbox extensions.

This schema is versioned separately from the thesis Mode B adapter; no claim of
exact prompt equivalence. All five own outcomes, public posts and prices enter.
"""
import json
import math
from dataclasses import asdict, replace
from repaired_engine import RepairedMarginAgent, Order, integer

PROMPT_VERSION='sandbox_outcomes_v1'

def strict_object(pairs):
    result={}
    for k,v in pairs:
        if k in result: raise ValueError('duplicate JSON key')
        result[k]=v
    return result

class RepairedLLMTrader(RepairedMarginAgent):
    def __init__(self,agent_id,cash,shares,rng,persona,client,allow_short=False,order_cap=10,**kwargs):
        super().__init__(agent_id,cash,shares,rng,allow_short=allow_short,**kwargs)
        self.persona=dict(persona); self.client=client
        self.last_raw_response=None; self.last_status='not_requested'; self.last_requested_order=None
        self.order_cap=integer(order_cap,'order cap',1)

    def parse_decision(self,raw):
        def failure(reason,status='error'): return Order(self.agent_id,'hold',0,None,reason,status)
        if not isinstance(raw,str) or not raw.strip(): return failure('empty response','missing')
        try:
            data=json.loads(raw,object_pairs_hook=strict_object,
                            parse_constant=lambda s: (_ for _ in ()).throw(ValueError('nonfinite JSON')))
            if not isinstance(data,dict) or set(data)!={'action','quantity','limit_price','reasoning'}:
                raise ValueError('exact schema fields required')
            side,q,p,reason=(data[k] for k in ('action','quantity','limit_price','reasoning'))
            if side not in ('buy','sell','hold') or type(q) is not int or q<0: raise ValueError('side/integer quantity')
            if not isinstance(reason,str) or not reason.strip(): raise ValueError('reasoning string required')
            if p is not None and (type(p) not in (int,float) or not math.isfinite(p) or p<=0): raise ValueError('positive numeric limit or null required')
            if side=='hold' and (q!=0 or p is not None): raise ValueError('HOLD must have zero quantity/null limit')
            if side!='hold' and q==0: side='hold'; p=None
            return Order(self.agent_id,side,q,p,reason)
        except (ValueError,TypeError,OverflowError) as exc: return failure(str(exc))

    def _build_prompt(self,obs,mark_p):
        # Episode length is researcher metadata, not disclosed as asset expiry.
        return json.dumps(dict(prompt_version=PROMPT_VERSION,persona=self.persona,
            rules=dict(auction='uniform call auction',tick=.1,price_band=.2,
                max_order_quantity=self.order_cap,
                short_selling=self.allow_short,initial_short_cash_ratio=self.initial_margin_ratio,
                maintenance_ratio=self.maint_margin_ratio,
                collateral='cash includes collateral; new shorts cannot use sale proceeds to reserve margin',
                maintenance='stop on breach; no guaranteed forced fills',
                income='post-trade shares receive/owe dividend; opening post-settlement cash earns interest',
                asset='perpetual; recording window does not terminate shares'),
            observation=dict(session=obs.round,prior_prices=obs.price_history[-10:],
                prior_volumes=obs.volume_history[-10:],previous_dividend=obs.last_dividend,
                dividend_label='initial prior, not a paid observation' if obs.round==1 else 'previous paid dividend',
                risk_free_rate=obs.risk_free_rate,disclosed_reference=obs.fundamental_hint,
                public_forum_posts=obs.bbs_posts,
                own_executed_outcomes=obs.own_outcomes[-5:]),
            account=dict(cash=self.cash,shares=self.shares,avg_cost=self.avg_cost,
                wealth=self.wealth(mark_p),initial_collateral=self.get_required_collateral(mark_p),
                free_cash=self.get_free_cash_at_price(mark_p)),
            response_schema=dict(action='buy|sell|hold',quantity='integer; zero only for hold',
                limit_price='positive number or null; hold requires null',reasoning='nonempty string')),
            ensure_ascii=False,allow_nan=False,sort_keys=True)

    def decide(self,obs):
        self.last_raw_response=None; self.last_requested_order=None
        messages=[dict(role='system',content='Trade using the supplied rules and information. Return only the specified JSON object.'),
                  dict(role='user',content=self._build_prompt(obs,obs.price_history[-1]))]
        try: self.last_raw_response=self.client.complete(messages,temperature=.3,max_tokens=2048)
        except Exception as exc:
            self.last_status='missing'
            return Order(self.agent_id,'hold',0,None,type(exc).__name__+': '+str(exc),'missing')
        requested=self.parse_decision(self.last_raw_response)
        self.last_requested_order=asdict(requested)
        if requested.status!='valid':
            self.last_status=requested.status
            return requested
        capped=replace(requested,quantity=min(requested.quantity,self.order_cap),
                       status='clipped' if requested.quantity>self.order_cap else requested.status)
        accepted=self.validate_orders(capped,obs.price_history[-1])[0]
        self.last_status=accepted.status
        return accepted
