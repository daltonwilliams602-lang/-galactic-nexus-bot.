"""Policy engine. No Discord requests occur inside database transactions."""
from dataclasses import dataclass, field
import copy
import difflib
import hashlib
import math
import re
import time
import uuid
from .storage import encode
from .blueprint import RANKS, FACTIONS, COUNCILS, PRESTIGE, OPT_INS, STAFF


class PolicyError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise PolicyError(message)


@dataclass(frozen=True)
class Actor:
    id: str
    roles: frozenset = field(default_factory=frozenset)
    current_staff: frozenset = field(default_factory=frozenset)


DEFAULTS = dict(mode='test', owner_id='', founder_ids=[], rank_thresholds=[0, 500, 3000, 14400, 151200],
    transfer_ranks=[0, 0, 1, 2, 2], xp_per_minute=10, faction_cooldown_days=30,
    voice_checkin_minutes=15, full_credit_minutes_per_day=240,
    reduced_credit_minutes_per_day=240, council_seats=12, campaign_days=30, inactivity_days=90)


class Engine:
    def __init__(self, store, config, clock=time.time):
        self.s, self.clock = store, clock
        self.c = DEFAULTS | config
        self.c['owner_id'] = str(self.c['owner_id'])
        self.c['founder_ids'] = [str(x) for x in self.c['founder_ids']]
        require(self.c['mode'] in ('test', 'live'), 'Unknown mode.')
        require(len(set(self.c['founder_ids'])) == len(self.c['founder_ids']), 'Duplicate founder IDs.')
        require(self.c['owner_id'] in self.c['founder_ids'], 'Owner must be explicitly included among the founders.')
        if self.c['mode'] == 'live':
            require(len(self.c['founder_ids']) == 4, 'Configure all four founders before live mode.')
            require(config.get('owner_approved_launch') is True, 'Owner launch approval must be recorded before live mode.')
        self.validate_curve(self.c['rank_thresholds'])
        require(len(self.c['transfer_ranks']) == 5 and all(isinstance(x, int) and 0 <= x <= 3 for x in self.c['transfer_ranks']), 'Invalid transfer ranks.')
        previous = self.s.get('meta', 'deployment')
        identity = {'guild_id': str(config.get('guild_id', '')), 'mode': self.c['mode']}
        require(previous is None or previous == identity, 'Database belongs to a different guild or mode. No changes made.')
        self.s.put('meta', 'deployment', identity)
        if self.s.get('meta', 'text_salt') is None:
            self.s.put('meta', 'text_salt', uuid.uuid4().hex)

    @staticmethod
    def validate_curve(curve):
        require(len(curve) == 5 and curve[0] == 0 and all(type(x) is int for x in curve)
                and all(a < b for a, b in zip(curve, curve[1:])), 'Thresholds must be five increasing integers starting at zero.')

    def config(self):
        return self.c | self.s.get('config', 'runtime', {})

    def member(self, uid):
        return self.s.get('member', uid, {'id': str(uid), 'accepted': False, 'path': None, 'alignment': None,
            'rank': 0, 'xp': 0, 'paths': {}, 'cooldown_until': 0, 'revision': 0, 'last_active': 0,
            'native_timeout_until': 0, 'restrictions': [], 'prestige': [], 'interests': []})

    def save_member(self, m, bump=True, sync=True):
        if bump:
            m['revision'] += 1
        self.s.put('member', m['id'], m)
        if sync:
            self.s.enqueue('roles', {'member': m['id']})

    def founder(self, actor):
        return actor.id in self.c['founder_ids']

    def staff(self, actor):
        return self.founder(actor) or bool(set(STAFF[1:]) & set(actor.roles))

    def authorize(self, a, action, target):
        require(bool(a.id), 'Unknown acting member.')
        if self.c['mode'] == 'test':
            require(self.founder(a), 'This server is in private founder testing.')
        self_actions = {'join', 'path', 'faction-request', 'interest', 'report', 'voice-check'}
        staff_actions = {'promotion-review', 'faction-review', 'award-xp', 'influence', 'standing', 'council-nominate'}
        founder_actions = {'override', 'prestige', 'council-vote', 'council-finalize', 'campaign-start',
            'campaign-finish', 'campaign-edit', 'configure', 'founder-test'}
        if action in self_actions:
            require(str(target) == a.id, 'This action is limited to your own account.')
        elif action in staff_actions:
            require(self.staff(a), 'An authorized staff role is required.')
        elif action in founder_actions:
            require(self.founder(a), 'Founding Council authorization is required.')
        elif action == 'council-emergency-remove':
            require(a.id == self.c['owner_id'], 'Only the actual server owner can use emergency removal.')
        else:
            raise PolicyError('Unknown action.')

    def fingerprint(self, action, target, args):
        if action in {'promotion-review', 'faction-review', 'council-vote', 'council-finalize'}:
            proposal = self.s.get('proposal', target)
            require(proposal is not None, 'Review item not found.')
            member = self.member(proposal['member'])
            data = [proposal, member['revision'], member['native_timeout_until'], member['restrictions']]
        elif action.startswith('campaign-') or action == 'influence':
            data = [self.s.all('campaign'), self.s.get('meta', 'active_campaign'), self.member(args.get('member', target))['revision']]
        elif action == 'configure':
            data = self.config()
        else:
            m = self.member(target)
            data = [m['revision'], m['native_timeout_until'], m['restrictions']]
            if action == 'override' and args.get('field') in {'xp', 'path_xp'}:
                data += [m['xp'], m['paths']]
        if action.startswith('council-') or action == 'founder-test':
            data = [data, self.s.all('council')]
        return hashlib.sha256(encode(data).encode()).hexdigest()

    def preview(self, actor, action, target, args=None):
        args = copy.deepcopy(args or {})
        args.setdefault('operation_id', uuid.uuid4().hex)
        self.authorize(actor, action, target)
        with self.s.transaction():
            expected = self.fingerprint(action, str(target), args)
            self.s.db.execute('SAVEPOINT preview')
            try:
                result = self._apply(actor, action, str(target), args)
            finally:
                self.s.db.execute('ROLLBACK TO preview')
                self.s.db.execute('RELEASE preview')
            token = uuid.uuid4().hex
            self.s.put('confirmation', token, {'actor': actor.id, 'action': action, 'target': str(target),
                'args': args, 'expected': expected, 'expires': self.clock() + 180, 'used': False})
        return token, result

    def confirm(self, actor, token):
        with self.s.transaction():
            item = self.s.get('confirmation', token)
            require(item is not None and item['actor'] == actor.id, 'This confirmation belongs to another member or is unavailable.')
            require(not item['used'] and self.clock() < item['expires'], 'Confirmation expired or already used. Preview again.')
            self.authorize(actor, item['action'], item['target'])
            require(item['expected'] == self.fingerprint(item['action'], item['target'], item['args']), 'The relevant state changed. Review a fresh confirmation.')
            result = self._apply(actor, item['action'], item['target'], item['args'])
            item['used'] = True
            self.s.put('confirmation', token, item)
            return result

    def active_restrictions(self, m):
        now = self.clock()
        notes = [r['reason'] for r in m['restrictions'] if not r.get('closed') and (not r.get('until') or r['until'] > now)]
        if m['native_timeout_until'] > now:
            notes.append('Active Discord timeout')
        return notes

    def eligible(self, m):
        if not m['accepted'] or m['path'] is None or m['rank'] >= 4:
            return False
        p = m['paths'][m['path']]
        return p['xp'] >= self.config()['rank_thresholds'][m['rank'] + 1]

    def queue_promotion(self, m, forced=False, reason='XP milestone reached'):
        # Callers applying commands/activity already own a transaction; standalone
        # reconciliation must commit rank, history, and delivery work together.
        if not self.s.db.in_transaction:
            with self.s.transaction():
                return self.queue_promotion(m, forced=forced, reason=reason)
        if not m['accepted'] or not m['path']:
            return None
        before = copy.deepcopy(m)
        while m['rank'] < 3 and self.eligible(m) and not self.active_restrictions(m):
            next_rank = m['rank'] + 1
            legacy = [(pid, q) for pid, q in self.s.all('proposal').items()
                      if q['kind'] == 'promotion' and q['member'] == m['id']
                      and q['path'] == m['path'] and q['rank'] == next_rank]
            # Preserve an explicit staff hold from the earlier manual policy.
            if any(q['status'] in {'deferred', 'denied'} for _, q in legacy):
                break
            m['rank'] = next_rank
            m['paths'][m['path']]['earned_rank'] = max(
                next_rank, m['paths'][m['path']]['earned_rank'])
            for pid, q in legacy:
                if q['status'] == 'pending':
                    q.update(status='superseded', resolution='XP threshold now advances this rank automatically')
                    self.s.put('proposal', pid, q)
        if m['rank'] != before['rank']:
            self.save_member(m)
            self.audit(Actor('system'), 'automatic-promotion', m['id'], before, m,
                       'Qualified XP threshold; approvals required only for Master/Lord')
        if m['rank'] < 3 or m['rank'] >= 4:
            return None
        if not forced and not self.eligible(m):
            return None
        require(m['path'] and m['rank'] < 4, 'No next progression rank.')
        next_rank = m['rank'] + 1
        candidates = self.s.all('proposal')
        for pid, q in candidates.items():
            if q['kind'] == 'promotion' and q['member'] == m['id'] and q['path'] == m['path'] and q['rank'] == next_rank and q['status'] in {'pending', 'deferred', 'denied'}:
                if forced and q['status'] != 'pending':
                    q.update(status='pending', approvals=[], forced=True, reason=reason)
                    self.s.put('proposal', pid, q)
                return pid
        pid = uuid.uuid4().hex[:12]
        q = {'id': pid, 'kind': 'promotion', 'member': m['id'], 'path': m['path'], 'from_rank': m['rank'],
             'rank': next_rank, 'forced': forced, 'approvals': [], 'status': 'pending', 'reason': reason,
             'member_revision': m['revision'], 'created_at': self.clock()}
        self.s.put('proposal', pid, q)
        self.s.enqueue('promotion', {'id': pid})
        return pid

    def close_member_proposals(self, uid, reason):
        for pid, q in self.s.all('proposal').items():
            if q['member'] == uid and q['status'] in {'pending', 'deferred'}:
                q.update(status='superseded', resolution=reason)
                self.s.put('proposal', pid, q)

    def audit(self, a, action, target, before, after, reason):
        self.s.log(a.id, action, target, before, after, reason, self.clock())
        self.s.enqueue('audit', {'actor': a.id, 'action': action, 'target': target, 'before': before,
            'after': after, 'reason': reason, 'mode': self.c['mode']})

    def switch_path(self, m, destination, bypass=False):
        require(m['accepted'], 'Accept the rules and confirm 17+ first.')
        require(destination in RANKS and destination != m['path'], 'Choose a different valid path.')
        require(bypass or self.clock() >= m['cooldown_until'], 'The 30-day faction cooldown is still active. Use /faction-request for an exception.')
        previous = m['path']
        if destination not in m['paths']:
            rank = self.config()['transfer_ranks'][m['rank']] if previous else 0
            m['paths'][destination] = {'xp': self.config()['rank_thresholds'][rank], 'earned_rank': 0, 'transferred_rank': rank}
        else:
            p = m['paths'][destination]
            rank = min(max(p['earned_rank'], p.get('transferred_rank', 0)), 3)
        m.update(path=destination, alignment='light' if destination == 'jedi' else 'dark', rank=rank,
                 cooldown_until=self.clock() + self.config()['faction_cooldown_days'] * 86400)
        for key, seat in self.s.all('council').items():
            if seat['member'] == m['id'] and seat['status'] == 'active':
                seat.setdefault('history', []).append({'at': self.clock(), 'previous': 'active', 'new': 'former', 'reason': 'Faction changed'})
                seat.update(status='former', ended_at=self.clock(), reason='Faction changed')
                self.s.put('council', key, seat)
        self.close_member_proposals(m['id'], 'Faction changed; previous approvals no longer apply')
        self.save_member(m)
        self.queue_promotion(m)
        return {'path': destination, 'rank': RANKS[destination][m['rank']], 'total_xp_preserved': m['xp'],
                'cooldown_days': self.config()['faction_cooldown_days'],
                'consequences': 'Previous Council access ends. Previously earned top ranks need fresh human review; history is retained.'}

    def _apply(self, a, action, target, args):
        m = self.member(target)
        before = copy.deepcopy(m)
        reason = str(args.get('reason', '')).strip()[:1500]
        if action not in {'join', 'path', 'interest', 'voice-check', 'council-vote'}:
            require(len(reason) >= 5, 'Give a specific reason of at least five characters.')
        if action == 'join':
            require(args.get('age_confirmed') is True and args.get('rules_accepted') is True,
                    'You must confirm that you are 17+ and accept the rules.')
            require(not m['accepted'], 'You already completed onboarding.')
            m.update(accepted=True, accepted_at=self.clock(), rules_version=1)
            self.save_member(m)
            self.s.enqueue('welcome', {'member': target}, ident='welcome:' + target)
            result = {'from': 'New arrival', 'to': 'Member + Force Sensitive', 'declaration': 'I am at least 17 and accept the community rules.'}
        elif action == 'path':
            result = self.switch_path(m, args.get('path'))
        elif action == 'faction-request':
            require(m['accepted'], 'Complete onboarding first.')
            require(args.get('path') in RANKS and args['path'] != m['path'], 'Choose the requested destination.')
            require(not any(q['kind'] == 'faction' and q['member'] == target and q['status'] == 'pending'
                            for q in self.s.all('proposal').values()), 'You already have an open faction request.')
            pid = args['operation_id'][:12]
            q = {'id': pid, 'kind': 'faction', 'member': target, 'path': args['path'], 'reason': reason,
                 'status': 'pending', 'member_revision': m['revision'], 'created_at': self.clock()}
            self.s.put('proposal', pid, q)
            self.s.enqueue('faction-request', {'id': pid})
            result = {'private_request': pid, 'destination': args['path'], 'current_path': m['path']}
        elif action == 'faction-review':
            q = self.s.get('proposal', target)
            require(q and q['kind'] == 'faction' and q['status'] == 'pending', 'No open faction request.')
            m = self.member(q['member'])
            before = copy.deepcopy(m)
            require(a.id != m['id'], 'Another staff member must review your request.')
            require(m['revision'] == q['member_revision'], 'Member state changed; request a fresh faction review.')
            require(args.get('decision') in {'approve', 'deny'}, 'Choose approve or deny.')
            if args['decision'] == 'approve':
                result = self.switch_path(m, q['path'], bypass=True)
            else:
                result = {'decision': 'Denied; faction and XP remain unchanged'}
            q.update(status='approved' if args['decision'] == 'approve' else 'denied', reviewer=a.id, resolution=reason)
            self.s.put('proposal', target, q)
        elif action == 'interest':
            require(m['accepted'], 'Complete onboarding first.')
            role = args.get('role')
            require(role in OPT_INS, 'That role is not self-assignable.')
            if role in m['interests']:
                m['interests'].remove(role)
            else:
                m['interests'].append(role)
            self.save_member(m)
            result = {'interests': m['interests']}
        elif action == 'voice-check':
            require(m['accepted'] and m['path'], 'Complete onboarding and choose a path first.')
            self.s.put('voice-check', target, {'until': self.clock() + self.config()['voice_checkin_minutes'] * 60})
            result = {'checkin_minutes': self.config()['voice_checkin_minutes'], 'note': 'Only eligible, attended voice minutes count. No audio is recorded.'}
        elif action == 'report':
            rid = args['operation_id'][:12]
            self.s.put('report', rid, {'member': target, 'reason': reason, 'status': 'open', 'at': self.clock()})
            self.s.enqueue('report', {'id': rid, 'member': target, 'reason': reason})
            result = {'private_report': rid, 'status': 'Sent to staff'}
        elif action == 'award-xp':
            require(m['accepted'] and m['path'], 'Member must complete onboarding and choose a path.')
            require(self.c['mode'] == 'test' or a.id != target, 'Have another staff member award your participation.')
            amount = int(args.get('amount', 0))
            require(0 < amount <= 10000, 'Event awards must be between 1 and 10,000 XP.')
            event = str(args.get('event_id', '')).strip()
            require(3 <= len(event) <= 120, 'Use a stable event ID to prevent duplicate awards.')
            require(not self.s.seen('event-xp:' + event + ':' + target, self.clock()), 'This member was already awarded XP for that event.')
            m['xp'] += amount
            m['paths'][m['path']]['xp'] += amount
            m['last_active'] = self.clock()
            self.save_member(m, bump=False, sync=False)
            pid = self.queue_promotion(m)
            result = {'previous_xp': before['xp'], 'new_xp': m['xp'], 'event': event, 'review': pid}
        elif action == 'standing':
            require(a.id != target, 'Another staff member must change your disciplinary standing.')
            if args.get('decision') == 'add':
                days = int(args.get('days', 30))
                require(0 <= days <= 3650, 'Choose 0 for an indefinite restriction, or up to 3,650 days.')
                m['restrictions'].append({'id': args['operation_id'][:12], 'reason': reason,
                    'at': self.clock(), 'until': self.clock() + days * 86400 if days else 0, 'actor': a.id})
            else:
                require(args.get('decision') == 'clear', 'Choose add or clear.')
                matches = [r for r in m['restrictions'] if r['id'] == args.get('restriction_id') and not r.get('closed')]
                require(bool(matches), 'Active restriction not found.')
                matches[0].update(closed=True, closed_at=self.clock(), closed_by=a.id, resolution=reason)
            self.save_member(m)
            result = {'standing': self.active_restrictions(m), 'xp_preserved': m['xp']}
        elif action in {'override', 'founder-test'}:
            testing = action == 'founder-test'
            require(not testing or (self.c['mode'] == 'test' and a.id == target), 'Testing tools affect only your own test account.')
            require(testing or self.c['mode'] == 'test' or a.id != target, 'Have another founder review your own live progression correction.')
            field_name, value = args.get('field'), args.get('value')
            require(m['accepted'], 'Complete onboarding first.')
            if field_name == 'faction':
                result = self.switch_path(m, str(value), bypass=True)
            elif field_name == 'rank':
                require(m['path'], 'Choose a faction first.')
                rank = int(value)
                require(0 <= rank <= 4, 'Rank must be 0 through 4.')
                if rank == 4 and not testing:
                    require(m['rank'] == 3, 'Top-rank review starts from Knight/Warrior; it still needs two staff approvals.')
                    pid = self.queue_promotion(m, forced=True, reason=reason)
                    result = {'high_promotion_review': pid, 'required_distinct_approvals': 2}
                else:
                    m['rank'] = rank
                    m['paths'][m['path']]['earned_rank'] = max(rank, m['paths'][m['path']]['earned_rank'])
                    self.close_member_proposals(target, 'Manual rank correction')
                    self.save_member(m)
                    result = {'rank': RANKS[m['path']][rank], 'xp_preserved': m['xp'], 'testing': testing}
            elif field_name in {'xp', 'path_xp'}:
                require(m['path'], 'Choose a path first.')
                amount = int(value)
                require(0 <= amount <= 1000000000, 'XP must be a non-negative integer, at most one billion.')
                if field_name == 'xp':
                    difference = amount - m['xp']
                    m['xp'] = amount
                    m['paths'][m['path']]['xp'] = max(0, m['paths'][m['path']]['xp'] + difference)
                else:
                    m['paths'][m['path']]['xp'] = amount
                self.save_member(m)
                self.queue_promotion(m)
                result = {'total_xp': m['xp'], 'path_xp': m['paths'][m['path']]['xp'], 'earned_ranks_retained': True}
            elif field_name == 'cooldown':
                hours = int(value)
                require(0 <= hours <= 8760, 'Cooldown must be 0–8,760 hours from now.')
                m['cooldown_until'] = self.clock() + hours * 3600
                self.save_member(m)
                result = {'cooldown_hours_from_now': hours}
            elif field_name == 'eligibility':
                pid = self.queue_promotion(m, forced=True, reason=reason)
                result = {'promotion_review': pid, 'note': 'Normal approval and standing checks still apply.'}
            elif field_name == 'council' and testing:
                require(value in {'active', 'inactive', 'former'} and m['path'], 'Use active, inactive, or former after choosing a faction.')
                key = m['path'] + ':' + target
                if value == 'active':
                    require(m['rank'] == 4, 'Simulate Master/Lord before testing a Council appointment.')
                    self.check_seat(m['path'], target)
                seat = self.s.get('council', key, {'member':target,'path':m['path'],'history':[]})
                seat.setdefault('history',[]).append({'at':self.clock(),'previous':seat.get('status'),
                    'new':value,'actor':a.id,'reason':reason,'test':True})
                seat.update(status=value,at=self.clock(),test=True)
                self.s.put('council', key, seat)
                self.save_member(m)
                result = {'test_council_status': value}
            else:
                raise PolicyError('Unsupported override field.')
        elif action == 'promotion-review':
            return self.review_promotion(a, target, args)
        elif action.startswith('council-'):
            return self.council_action(a, action, target, args)
        elif action.startswith('campaign-') or action == 'influence':
            return self.campaign_action(a, action, target, args)
        elif action == 'prestige':
            title = args.get('title')
            require(title in PRESTIGE and m['path'] == PRESTIGE[title], 'That title belongs to the other path, or is invalid.')
            require(args.get('decision') in {'grant', 'remove'}, 'Choose grant or remove.')
            if args['decision'] == 'grant':
                if title not in m['prestige']:
                    m['prestige'].append(title)
            elif title in m['prestige']:
                m['prestige'].remove(title)
            self.save_member(m)
            result = {'prestige_titles': m['prestige']}
        elif action == 'configure':
            key, value = args.get('key'), args.get('value')
            allowed = {'rank_thresholds', 'transfer_ranks', 'faction_cooldown_days', 'voice_checkin_minutes',
                'campaign_days', 'inactivity_days', 'xp_per_minute'}
            require(key in allowed, 'That setting is not editable through Discord.')
            if key == 'rank_thresholds':
                self.validate_curve(value)
            elif key == 'transfer_ranks':
                require(isinstance(value, list) and len(value) == 5 and value[0] == 0 and all(type(x) is int and 0 <= x <= min(i, 3) for i, x in enumerate(value)), 'Invalid transfer mapping; a new path cannot start at Master/Lord.')
            else:
                require(type(value) is int and 1 <= value <= 365, 'Choose a positive integer up to 365.')
                if key == 'voice_checkin_minutes':
                    require(value <= 30, 'Voice presence checks may not exceed 30 minutes.')
            old = self.config().get(key)
            overrides = self.s.get('config', 'runtime', {})
            overrides[key] = value
            self.s.put('config', 'runtime', overrides)
            self.audit(a, action, key, old, value, reason)
            return {'setting': key, 'previous': old, 'proposed': value, 'history_preserved': True}
        else:
            raise PolicyError('Action is not implemented.')
        self.audit(a, action, target, before, {'member': m, 'result': result}, reason or action)
        return {'action': action, 'affected_member': m['id'], 'current_path': before.get('path'),
                'current_rank': before.get('rank'), 'proposed': result}

    def review_promotion(self, a, pid, args):
        q = self.s.get('proposal', pid)
        require(q and q['kind'] == 'promotion' and q['status'] in {'pending', 'deferred'}, 'No open promotion review.')
        m = self.member(q['member'])
        require(a.id != m['id'], 'You cannot approve or adjudicate your own promotion.')
        require(m['path'] == q['path'] and m['rank'] == q['from_rank'], 'This review no longer matches the member. Create a fresh review.')
        before = copy.deepcopy(q)
        decision, reason = args.get('decision'), args['reason']
        require(decision in {'approve', 'defer', 'deny', 'reopen'}, 'Choose approve, defer, deny, or reopen.')
        if decision == 'approve':
            require(q['status'] == 'pending', 'Reopen the deferred review before approving.')
            require(not self.active_restrictions(m), 'Active disciplinary restrictions block approval. Defer for staff review; XP remains intact.')
            require(q.get('forced') or self.eligible(m), 'Member is no longer eligible at the current threshold.')
            # Revalidate earlier approvers against the adapter's current membership/role snapshot.
            authorized = set(a.current_staff)
            q['approvals'] = [uid for uid in q['approvals'] if uid in authorized and uid != m['id']]
            require(a.id not in q['approvals'], 'Your approval is already recorded.')
            q['approvals'].append(a.id)
            required = 2 if q['rank'] == 4 else 1
            if len(q['approvals']) >= required:
                m['rank'] = q['rank']
                p = m['paths'][m['path']]
                p['earned_rank'] = max(p['earned_rank'], m['rank'])
                self.save_member(m)
                q.update(status='approved', finalized_by=a.id, finalized_at=self.clock())
            q['required'] = required
        elif decision == 'reopen':
            q.update(status='pending', approvals=[])
        else:
            q.update(status='deferred' if decision == 'defer' else 'denied', approvals=[])
        q['resolution'] = reason
        self.s.put('proposal', pid, q)
        self.audit(a, 'promotion-' + decision, m['id'], before, q, reason)
        if q['status'] == 'approved':
            self.queue_promotion(m)
        return {'review': pid, 'affected_member': m['id'], 'faction': q['path'], 'current_rank': RANKS[q['path']][q['from_rank']],
            'proposed_rank': RANKS[q['path']][q['rank']], 'path_xp': m['paths'][q['path']]['xp'],
            'standing': self.active_restrictions(m), 'approvals': q['approvals'], 'required': 2 if q['rank'] == 4 else 1,
            'result': q['status'], 'earned_xp_preserved': m['xp']}

    def check_seat(self, path, uid):
        seats = [v for v in self.s.all('council').values() if v['path'] == path and v['status'] == 'active' and v['member'] != uid]
        require(len(seats) < min(12, self.config()['council_seats']), 'All 12 active Council seats are occupied.')

    def council_action(self, a, action, target, args):
        reason = args.get('reason', 'Founder vote')
        if action == 'council-emergency-remove':
            m = self.member(target)
            before = []
            for key, seat in self.s.all('council').items():
                if seat['member'] == target and seat['status'] == 'active':
                    before.append(copy.deepcopy(seat))
                    seat.setdefault('history',[]).append({'at':self.clock(),'previous':seat['status'],
                        'new':'removed','actor':a.id,'reason':reason,'emergency':True})
                    seat.update(status='removed', reason=reason, ended_at=self.clock(), emergency_owner=a.id)
                    self.s.put('council', key, seat)
            require(bool(before), 'Member has no active lore Council seat.')
            self.save_member(m)
            self.audit(a, action, target, before, 'Emergency removal', reason)
            return {'member': target, 'result': 'Emergency lore Council removal; founder status and XP preserved.'}
        if action == 'council-nominate':
            m = self.member(target)
            purpose = args.get('purpose')
            require(purpose in {'appoint', 'remove', 'inactive', 'restore'}, 'Unknown Council motion.')
            path = args.get('path', m['path'])
            require(path in RANKS, 'Choose Jedi or Sith.')
            seat = self.s.get('council', path + ':' + target)
            if purpose in {'appoint', 'restore'}:
                require(m['path'] == path and m['rank'] == 4, 'Candidate must currently be a Master/Lord of this path.')
                require(not self.active_restrictions(m), 'Resolve active standing restrictions before nomination.')
                require(not seat or seat['status'] != 'active', 'Candidate already has an active seat.')
                self.check_seat(path, target)
            else:
                require(seat and seat['status'] == 'active', 'No active seat for this motion.')
                if purpose == 'inactive':
                    require(self.clock() - m['last_active'] >= self.config()['inactivity_days'] * 86400,
                            'Inactivity consideration begins after the configured 90-day period.')
            require(not any(v['kind'] == 'council' and v['member'] == target and v['status'] == 'pending'
                            for v in self.s.all('proposal').values()), 'This candidate already has an open Council motion.')
            pid = args['operation_id'][:12]
            q = {'id': pid, 'kind': 'council', 'member': target, 'path': path, 'purpose': purpose,
                 'status': 'pending', 'reason': reason, 'votes': {}, 'nominator': a.id, 'created_at': self.clock()}
            self.s.put('proposal', pid, q)
            self.s.enqueue('council', {'id': pid})
            self.audit(a, action, target, None, q, reason)
            return {'nomination': pid, 'purpose': purpose, 'required': 'Three yes votes from the four founders, then human confirmation.'}
        q = self.s.get('proposal', target)
        require(q and q['kind'] == 'council' and q['status'] == 'pending', 'No open Council motion.')
        before = copy.deepcopy(q)
        if action == 'council-vote':
            require(a.id != q['member'], 'The subject must recuse from their own Council vote.')
            vote = args.get('vote')
            require(vote in {'yes', 'no', 'abstain'}, 'Choose yes, no, or abstain.')
            q['votes'][a.id] = vote
        elif action == 'council-finalize':
            require(len(self.c['founder_ids']) == 4, 'All four founders must be explicitly configured before a Council decision.')
            require(a.id != q['member'], 'Another founder must confirm this Council decision.')
            yes = sum(v == 'yes' for uid, v in q['votes'].items() if uid in self.c['founder_ids'] and uid != q['member'])
            needed = math.ceil(4 * (3/4 if q['purpose'] in {'remove', 'inactive'} else 2/3))
            require(yes >= needed, f'{needed} yes votes from the full four-founder roster are required; abstentions do not reduce the threshold.')
            m = self.member(q['member'])
            key = q['path'] + ':' + m['id']
            seat = self.s.get('council', key, {'member': m['id'], 'path': q['path'], 'history': []})
            seat.setdefault('history', [])
            if q['purpose'] in {'appoint', 'restore'}:
                require(m['path'] == q['path'] and m['rank'] == 4 and not self.active_restrictions(m), 'Candidate is no longer eligible.')
                self.check_seat(q['path'], m['id'])
                status = 'active'
            else:
                require(seat.get('status') == 'active', 'Seat is no longer active.')
                status = 'inactive' if q['purpose'] == 'inactive' else 'removed'
            seat['history'].append({'at': self.clock(), 'previous': seat.get('status'), 'new': status, 'motion': target, 'reason': reason, 'actor': a.id})
            seat.update(status=status, at=self.clock(), reason=reason)
            self.s.put('council', key, seat)
            self.save_member(m)
            q.update(status='finalized', finalized_by=a.id, finalized_at=self.clock())
        else:
            raise PolicyError('Unknown Council action.')
        self.s.put('proposal', target, q)
        self.audit(a, action, q['member'], before, q, reason)
        return {'motion': target, 'member': q['member'], 'purpose': q['purpose'], 'votes': q['votes'],
                'status': q['status'], 'note': 'Votes alone never execute Council changes.'}

    def campaign_action(self, a, action, target, args):
        reason = args['reason']
        active_id = self.s.get('meta', 'active_campaign')
        active = self.s.get('campaign', active_id) if active_id else None
        before = copy.deepcopy(active)
        if action == 'campaign-start':
            require(not active or active['status'] == 'closed', 'Finish the current campaign before starting another.')
            days = int(args.get('days', self.config()['campaign_days']))
            require(1 <= days <= 365, 'Campaign duration must be 1–365 days.')
            name = str(args.get('name', '')).strip()
            require(3 <= len(name) <= 80, 'Use a campaign name of 3–80 characters.')
            cid = args['operation_id'][:12]
            active = {'id': cid, 'name': name, 'status': 'active', 'started_at': self.clock(),
                'ends_at': self.clock() + days * 86400, 'scores': {'jedi': 0, 'sith': 0}, 'winner': None,
                'planet_control': {}, 'rules_version': 1}
            self.s.put('meta', 'active_campaign', cid)
        else:
            require(active and active['status'] == 'active', 'There is no active campaign.')
            cid = active['id']
            if action == 'influence':
                require(self.clock() < active['ends_at'], 'The scoring period ended. A founder must review and finalize the result.')
                m = self.member(target)
                require(m['accepted'] and m['path'], 'Member must have a faction.')
                require(self.c['mode'] == 'test' or a.id != target, 'Another staff member must award your Influence.')
                amount = int(args.get('amount', 0))
                require(amount != 0 and abs(amount) <= 10000, 'Adjustment must be nonzero and within ±10,000 points.')
                require(amount > 0 or self.founder(a), 'A founder must review negative Influence corrections.')
                event = str(args.get('event_id', '')).strip()
                require(3 <= len(event) <= 120, 'Supply a stable event/mission ID for duplicate protection.')
                receipt = f'influence:{cid}:{event}:{target}'
                require(not self.s.seen(receipt, self.clock()), 'This event/member Influence award is already recorded.')
                require(active['scores'][m['path']] + amount >= 0, 'Faction score cannot become negative.')
                active['scores'][m['path']] += amount
                self.s.put('contribution', args['operation_id'], {'campaign': cid, 'member': target,
                    'path': m['path'], 'alignment': m['alignment'], 'amount': amount, 'event_id': event,
                    'planet_id': None, 'reason': reason, 'staff': a.id, 'at': self.clock()})
                m['last_active'] = self.clock()
                self.save_member(m, bump=False, sync=False)
            elif action == 'campaign-edit':
                days = int(args.get('days', 0))
                require(1 <= days <= 365, 'Duration must be 1–365 days from the original start.')
                active['ends_at'] = active['started_at'] + days * 86400
                if args.get('name'):
                    require(3 <= len(args['name']) <= 80, 'Name must have 3–80 characters.')
                    active['name'] = args['name']
            elif action == 'campaign-finish':
                require(self.clock() >= active['ends_at'] or a.id == self.c['owner_id'], 'Only the owner can explicitly end a season early.')
                scores = active['scores']
                winner = None if scores['jedi'] == scores['sith'] else max(scores, key=scores.get)
                active.update(status='closed', winner=winner, closed_at=self.clock(), finalized_by=a.id,
                    winning_members=[uid for uid, m in self.s.all('member').items() if winner and m['path'] == winner])
                self.s.put('meta', 'current_champion', cid)
                self.s.enqueue('campaign-result', {'id': cid})
                for uid in self.s.all('member'):
                    self.s.enqueue('roles', {'member': uid})
            else:
                raise PolicyError('Unknown campaign operation.')
        self.s.put('campaign', cid, active)
        self.audit(a, action, target, before, active, reason)
        return {'campaign': cid, 'name': active['name'], 'scores': active['scores'], 'status': active['status'],
            'winner': active['winner'], 'ends_at': active['ends_at'], 'history_preserved': True}

    def award_activity(self, uid, source, *, content='', event_id='', eligible_voice=False, now=None):
        """One shared minute slot for text and voice, with durable duplicate receipts."""
        now = self.clock() if now is None else now
        require(source in {'text', 'voice'}, 'Unknown activity source.')
        with self.s.transaction():
            m = self.member(uid)
            if self.c['mode'] == 'test' and str(uid) not in self.c['founder_ids']:
                return 0
            if not m['accepted'] or not m['path'] or m['native_timeout_until'] > now:
                return 0
            if source == 'text':
                normal = ' '.join(re.findall(r'[^\W\d_]+', content.casefold()))
                if content.lstrip().startswith(('/', '!', '?', '.')) or len(normal) < 20 or len(normal.split()) < 4:
                    return 0
                recent = self.s.get('last-text', uid, {})
                salt = self.s.get('meta', 'text_salt')
                tokens = [hashlib.sha256((salt+word).encode()).hexdigest() for word in normal.split()]
                if recent.get('at', 0) > now - 1800 and difflib.SequenceMatcher(None, tokens, recent.get('tokens', [])).ratio() > .90:
                    return 0
                digest = hashlib.sha256((salt+normal).encode()).hexdigest()
                if self.s.seen(f'message:{event_id}', now):
                    return 0
                if self.s.get('recent-text', str(uid) + ':' + digest, {}).get('at', 0) > now - 86400:
                    return 0
            else:
                check = self.s.get('voice-check', uid, {})
                if not eligible_voice or check.get('until', 0) <= now:
                    return 0
            # At most one reward per real 60 seconds and per minute bucket, across both modalities.
            previous = self.s.get('activity-clock', uid, {'at': -1000})
            if now - previous['at'] < 60 or self.s.seen(f'activity:{uid}:{int(now // 60)}', now):
                return 0
            day_key = f'{uid}:{int(now // 86400)}'
            daily = self.s.get('daily', day_key, {'minutes': 0})
            cfg = self.config()
            n = daily['minutes']
            if n >= cfg['full_credit_minutes_per_day'] + cfg['reduced_credit_minutes_per_day']:
                return 0
            amount = cfg['xp_per_minute'] if n < cfg['full_credit_minutes_per_day'] else max(1, cfg['xp_per_minute'] // 5)
            daily['minutes'] += 1
            self.s.put('daily', day_key, daily)
            self.s.put('activity-clock', uid, {'at': now})
            if source == 'text':
                self.s.put('recent-text', str(uid) + ':' + digest, {'at': now})
                self.s.put('last-text', uid, {'at': now, 'tokens': tokens})
                self.s.put('voice-check', uid, {'until': now + cfg['voice_checkin_minutes'] * 60})
            m['xp'] += amount
            m['paths'][m['path']]['xp'] += amount
            m['last_active'] = now
            self.save_member(m, bump=False, sync=False)
            self.s.log('system', 'activity-' + source, uid, m['xp'] - amount, m['xp'], 'Qualified minute', now)
            self.queue_promotion(m)
            return amount

    def desired_roles(self, uid):
        m = self.member(uid)
        roles = set(m['interests'])
        if not m['accepted']:
            return set()
        roles.add('Member')
        roles.add(RANKS[m['path']][m['rank']] if m['path'] else 'Force Sensitive')
        if m['path']:
            roles.add(FACTIONS[m['path']])
        for seat in self.s.all('council').values():
            if seat['member'] == str(uid):
                if seat['status'] == 'active' and seat['path'] == m['path']:
                    roles.add(COUNCILS[seat['path']])
                elif seat['status'] == 'inactive':
                    roles.add('Inactive Council')
        roles |= {r for r in m['prestige'] if PRESTIGE.get(r) == m['path']}
        champion_id = self.s.get('meta', 'current_champion')
        champion = self.s.get('campaign', champion_id) if champion_id else None
        if champion and str(uid) in champion.get('winning_members', []) and m['path'] == champion['winner']:
            roles.add('Rulers of the Galaxy')
        if self.c['mode'] == 'test' and str(uid) in self.c['founder_ids']:
            roles.add('Founder Tester')
        return roles
