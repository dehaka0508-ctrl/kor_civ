"""지도자 효과의 공통 계산. 미리보기·실행·AI가 같은 함수를 사용한다."""
from __future__ import annotations

from . import config as C, diplomacy as D, metro as M
from .state import NEUTRAL


class LeaderRulesMixin:
    def migrate_leader_state(self):
        for f in self.factions:
            if "original_regions" not in f.__dict__:
                f.original_regions = {r.id for r in self.regions_of(f.id)} | {
                    r.id for r in self.regions.values() if r.war_from == f.id}
            if "attacked_by" not in f.__dict__:
                f.attacked_by = {next(x for x in pair if x != f.id) for pair, war in self.dip.wars.items()
                                 if f.id in pair and war.get("aggressor") not in (None, f.id)}
            if "lost_regions" not in f.__dict__:
                f.lost_regions = {r.id for r in self.regions.values() if r.war_from == f.id}
            if "coastal_rewards" not in f.__dict__:
                f.coastal_rewards = set()
                limit = self.mods(f.id).value("free_coastal_ports", 0)
                coast = sorted((r for r in self.regions_of(f.id) if self.info(r.id).coastal),
                               key=lambda r: (r.acquired_seq, r.id))
                for r in coast:
                    if len(f.coastal_rewards) >= limit:
                        break
                    if r.b.get("port"):
                        continue
                    f.coastal_rewards.add(r.id)
                    r.b.add_free("port", 1)
            f.tax = min(f.tax, self.tax_max(f.id))
        self._minority = {}

    def leader_acquired(self, fid, rid):
        if fid == NEUTRAL:
            return
        f = self.factions[fid]
        f.original_regions.add(rid)
        limit = self.mods(fid).value("free_coastal_ports", 0)
        b = self.regions[rid].b
        if limit and self.info(rid).coastal and rid not in f.coastal_rewards and len(f.coastal_rewards) < limit \
                and not b.get("port") and not self.has_port(rid):
            f.coastal_rewards.add(rid)          # 기타 슬롯에 붙여 꽂는다 — 해안 슬롯을 차지하지 않음(v1.3.9)
            b.add_free("port", 1)

    def unit_oil(self, fid, key):
        base = self.unit_spec(fid, key)["oil"]
        if key == "tank" or C.UNITS[key]["kind"] in ("air", "naval"):
            base += int(self.mods(fid).add("extra_unit_oil"))
        return base

    def unit_turns(self, fid, key):
        return self.unit_spec(fid, key)["turns"] + (int(self.mods(fid).add("naval_turns_add"))
                                                   if C.UNITS[key]["kind"] == "naval" else 0)

    def artillery_range(self, fid):
        return C.ART_RANGE + int(self.mods(fid).add("art_range_add"))

    def naval_bomb_range(self, fid):
        return C.NAVAL_BOMB_RANGE + (0 if self.naval_buff_off(fid) else int(self.mods(fid).add("naval_range_add")))

    def naval_steps(self, army):
        return C.NAVAL_STEPS + (int(self.mods(army.owner).add("lst_move_add")) if army.units.get("lst") else 0)

    def leader_unit_defense(self, army, key):
        return self.unit_spec(army.owner, key)["df"]

    def leader_defense_mult(self, fid, source, target):
        if fid != NEUTRAL and source in self.regions:
            terrain = self.world.terrain_between(source, target)
            if terrain and terrain["kind"] in ("돌파", "산악 돌파"):
                return self.mods(fid).mult("mountain_defense")
        return 1.0

    def connected_land(self, fid):
        cap = self.factions[fid].capital
        seen, todo = {cap}, [cap]
        while todo:
            for n in self.world.land_adj[todo.pop()]:
                if n not in seen and self.regions[n].owner == fid:
                    seen.add(n)
                    todo.append(n)
        return seen

    def leader_attack_mult(self, fid, source, target, units, mode="assault", enemy=None):
        if fid == NEUTRAL:
            return 1.0
        f, m = self.factions[fid], self.mods(fid)
        if enemy is None and target in self.regions:
            enemy = self.regions[target].owner
            if enemy == NEUTRAL:
                defenders = self.hostile_units_at(fid, target)
                enemy = defenders[0].owner if defenders else NEUTRAL
        value = 1.0
        if not any(D.allied(self, fid, x) for x in self.alive_ids() if x != fid):
            value *= m.mult("no_allies_atk")
        if enemy not in (None, NEUTRAL, fid):
            war = self.dip.wars.get(D.pair(fid, enemy), {})
            if enemy in f.attacked_by and war.get("declarer") == fid:
                value *= m.mult("revenge_attack")
            if self.gdp(enemy) > self.gdp(fid):
                value *= m.mult("richer_attack")
            if mode == "assault" and fid in war.get("coalition_declarers", ()):
                value *= m.mult("coalition_declare_atk")
            if target in self.regions:
                if target in f.lost_regions:
                    value *= m.mult("original_attack")
                unhappy = max(0, -self.eff_happy(self.regions[target]))
                value *= 1 + m.add("unhappy_enemy_atk") * min(1, unhappy / 100)
        if source in self.regions:
            if target in self.regions:
                terr = self.world.terrain_between(source, target)
                if terr and terr["kind"] in ("돌파", "산악 돌파"):
                    value *= m.mult("mountain_attack")
            if (target if target in self.regions else source) not in self.near_capital(fid, int(m.value("expedition_range", 5))):
                value *= m.mult("expedition_attack")
            if m.has("disconnected_attack") and source not in self.connected_land(fid):
                value *= m.mult("disconnected_attack")
        if units.get("inf") and units.get("tank"):
            value *= m.mult("mixed_inftank_atk")
        return value

    def leader_bank_mult(self, fid, rid):
        city = fid != NEUTRAL and (rid == self.factions[fid].capital or M.of(self, rid))
        return self.mods(fid).mult("city_bank_output") if city else 1.0

    def leader_output_mult(self, rid):
        r = self.regions[rid]
        if r.owner == NEUTRAL:
            return 1.0
        m = self.mods(r.owner)
        mult = m.mult("island_output") if self.info(rid).island else 1.0
        near = {rid} | set(self.world.land_adj[rid])
        if any(self.regions[x].owner == r.owner and "observatory" in self.regions[x].sci
               and not self.facility_paused(x) for x in near):
            mult *= m.mult("observatory_output")
        if self.turn < r.suppress_output_until:
            mult *= m.mult("suppress_output")
        return mult

    def focus_multiplier(self, fid):
        return self.mods(fid).value("focus_mult", 1)

    def release_focus(self, rr):
        if rr.focus:
            rr.focus_unrest_until = self.turn + int(self.mods(rr.owner).value("focus_release_turns", 0))
        rr.focus = False

    def facility_paused(self, rid):
        return self.turn < self.regions[rid].facility_off_until

    def leader_capture_effects(self, fid, rid, old):
        if old == NEUTRAL or old == fid:
            return
        m, r = self.mods(fid), self.regions[rid]
        r.pop = max(.1, r.pop * (1 - m.add("capture_pop_loss")))
        for a in self.armies_at(rid, fid):
            for k in list(a.dmg):
                a.dmg[k] = max(0, a.dmg[k] - a.hp_max(k) * m.add("capture_heal"))

    def leader_units_completed(self, fid, rid, key, n=1):
        r = self.queue_region(rid)
        if not self.mods(fid).value("unit_triplet") or key not in ("inf", "art"):
            r.unit_chain_count = 0
            return n
        r.unit_chain_count += 1
        return n + int(r.unit_chain_count % 3 == 0)

    def percent_damage(self, army, fraction, kinds=None):
        # 종류별 최대 체력 기준. 선박 침몰 시 수송 정원도 같은 실행에서 정리한다.
        for key in list(army.units):
            if kinds is not None and C.UNITS[key]["kind"] not in kinds:
                continue
            self.apply_damage([army], army.hp_max(key) * fraction, unit_filter=(key,))
            if army.id not in self.armies:
                break
        if army.id in self.armies:
            self._validate_capacity(army)

    def leader_attrition(self):
        for a in list(self.armies.values()):
            if a.owner == NEUTRAL:
                continue
            m = self.mods(a.owner)
            if self.world.is_sea(a.loc) and a.domain() == "naval" and m.add("naval_attrition"):
                self.percent_damage(a, m.add("naval_attrition"), ("naval",))
            elif a.loc in self.regions and self.regions[a.loc].owner == a.owner \
                    and self.resisting(self.regions[a.loc]) and m.add("guerrilla_percent"):
                self.percent_damage(a, m.add("guerrilla_percent"))

    def leader_battle_win(self, fid, enemy, eligible=None):
        if enemy in (NEUTRAL, fid) or not self.mods(fid).value("victory_loot"):
            return
        if eligible is False or (eligible is None and self.gdp(enemy) <= self.gdp(fid)):
            return
        amount = max(0, self.factions[enemy].money) * self.mods(fid).add("victory_loot")
        self.factions[enemy].money -= amount
        self.factions[fid].money += amount
        if amount:
            self.event("battle", f"활빈당: {self.fname(enemy)} 자금 {amount:,.0f} 약탈", fids=(fid, enemy))

    def refresh_joint_costs(self):
        for f in self.factions:
            if not self.mods(f.id).value("joint_cost_reduction"):
                continue
            projects = [p for p in self.unique_projects(self.regions_of(f.id)) if p.kind == "annex"]
            for p in projects:
                n = sum(self.annex_weight(q) for q in projects if q.key == p.key)
                p.per_turn = self.annex_cost(f.id, p.key, n) / max(1, p.turns)

    def leader_tax_revenue(self, fid):
        f, m = self.factions[fid], self.mods(fid)
        total = 0.0
        for r in self.regions_of(fid):
            output = r.output
            if m.value("resist_tax") and self.resist_phase(r)[0] in ("resist", "recover"):
                output = self.calc_output(r.id, full=True, ignore_resistance=True) * m.value("resist_tax")
            if M.of(self, r.id):
                output *= m.mult("metro_tax")
            total += output
        return total * f.tax * f.income_mult

    def leader_bomb_mult(self, fid, source, target, units):
        value = self.leader_attack_mult(fid, source, target, units, "bombard")
        if max(self.regions[target].lines.values(), default=0) >= 2:
            value *= self.mods(fid).mult("strong_line_bomb")
        return value

    def bomb_building_probability(self, fid, guns, bombers):
        from . import rules as R
        return min(1, R.bomb_building_chance(guns, bombers) +
                   (self.mods(fid).add("bomber_building_chance") if bombers else 0))

    def post_attack_options(self, army):
        return {n: {"action": "move", "path": [n], "strong": False}
                for n in self.world.land_adj.get(army.loc, ())
                if not self.hostile_units_at(army.owner, n)
                and self.may_enter(army.owner, n)}
