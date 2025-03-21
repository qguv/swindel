from collections import OrderedDict
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from exceptions import GameError
from items import Items

# true is live, false is blank
type ShellType = bool

@dataclass
class RoundState:
    total_live_shells: int
    total_blank_shells: int
    past_shells: List[ShellType] = field(default_factory=list)
    is_players_turn: bool = True
    gun_is_sawed: bool = False
    handcuffed_player_names: Set[str] = field(default_factory=set)
    known_shells: Dict[int, ShellType] = field(default_factory=dict)

    def remaining_live_shells(self) -> int:
        return self.total_live_shells - sum(1 for is_live in self.past_shells if is_live)

    def remaining_blank_shells(self) -> int:
        return self.total_blank_shells - sum(1 for is_live in self.past_shells if not is_live)

    def total_shells(self) -> int:
        return self.total_live_shells + self.total_blank_shells

    def learn_future_shell(self, shells_from_now, is_live):
        self.assert_future_shell(shells_from_now, is_live)
        self.known_shells[len(self.past_shells) + shells_from_now] = is_live

    def assert_future_shell(self, shells_from_now, is_live):

        # are there enough shells?
        i = len(self.past_shells) + shells_from_now
        if i >= self.total_shells():
            raise GameError("actually, there aren't enough shells to learn that!")

        # does it contradict with something we learned
        try:
            known_shell_is_live = self.known_shells[i]
            if known_shell_is_live != is_live:
                raise GameError(f"actually, player knows this shell to be {"live" if known_shell_is_live else "blank"}")

        # does it contradict with something we can deduce based on shell count
        except KeyError as e:
            remaining_matching_shells = self.remaining_live_shells() if is_live else self.remaining_blank_shells()
            if remaining_matching_shells < 1:
                raise GameError(f"actually, there are no {"live" if is_live else "blank"} shells left") from e

    def chance_shell_is_live(self):

        # are there enough shells?
        i = len(self.past_shells)
        if i >= self.total_shells():
            raise GameError("actually, there aren't enough shells to learn that!")

        # have we already learned it?
        try:
            return 1.0 if self.known_shells[i] else 0.0

        # does it contradict with something we can deduce based on shell count
        except KeyError:
            return self.remaining_live_shells() / self.total_shells()


    def raw_eject_shell(self, is_live):
        self.assert_future_shell(0, is_live)
        self.past_shells.append(is_live)

@dataclass
class Player:
    charges: int
    items: List[Items] = field(default_factory=list)
    is_critical: bool = False

@dataclass
class PhaseState:
    players: OrderedDict[str, Player]
    max_charges: int
    critical_charges: int = 0
    round: Optional[RoundState] = None
    num_completed_rounds: int = 0

    def eject_shell(self, is_live):
        self.round.raw_eject_shell(is_live)

        # if no shells left, end round
        if len(self.round.past_shells) == self.round.total_shells():
            self.round = None
            self.num_completed_rounds += 1

    def win_probability(self, player_name, depth=1):
        if self.round is None:
            print(" " * depth, "no winner") # DEBUG
            return 0.0
        opponent_name = "dealer" if player_name == "player" else "player"
        if self.players[player_name].charges <= 0:
            print(" " * depth, opponent_name, "wins") # DEBUG
            return 0.0
        if self.players[opponent_name].charges <= 0:
            print (" " * depth, player_name, "wins") # DEBUG
            return 1.0
        live_chance = self.round.chance_shell_is_live()
        blank_chance = 1.0 - live_chance

        # FIXME not correctly simulating opponent turns by reversing polarity!!!
        try:
            shoot_dealer_live_win_chance = 0.0
            if live_chance > 0.0:
                shoot_dealer_live = deepcopy(self)
                shoot_dealer_live.raw_shoot("dealer", True)
                shoot_dealer_live_win_chance = shoot_dealer_live.win_probability(player_name, depth=depth+1) * live_chance

            shoot_dealer_blank_win_chance = 0.0
            if blank_chance > 0.0:
                shoot_dealer_blank = deepcopy(self)
                shoot_dealer_blank.raw_shoot("dealer", False)
                shoot_dealer_blank_win_chance = shoot_dealer_blank.win_probability(player_name, depth=depth+1) * blank_chance

            shoot_player_live_win_chance = 0.0
            if live_chance > 0.0:
                shoot_player_live = deepcopy(self)
                shoot_player_live.raw_shoot("player", True)
                shoot_player_live_win_chance = shoot_player_live.win_probability(player_name, depth=depth+1) * live_chance

            shoot_player_blank_win_chance = 0.0
            if blank_chance > 0.0:
                shoot_player_blank = deepcopy(self)
                shoot_player_blank.raw_shoot("player", False)
                shoot_player_blank_win_chance = shoot_player_blank.win_probability(player_name, depth=depth+1) * blank_chance
        except GameError:
            return 0.0

        shoot_dealer_win_chance = shoot_dealer_live_win_chance + shoot_dealer_blank_win_chance
        shoot_player_win_chance = shoot_player_live_win_chance + shoot_player_blank_win_chance
        if shoot_player_win_chance > shoot_dealer_win_chance:
            print(" " * depth, "player" if self.round.is_players_turn else "dealer", "shoots player")
        else:
            print(" " * depth, "player" if self.round.is_players_turn else "dealer", "shoots dealer")
        return max(shoot_dealer_win_chance, shoot_player_win_chance)

    def raw_shoot(self, target_name, is_live):

        # check if this is possible given what we know
        self.round.assert_future_shell(0, is_live)

        if is_live:

            if self.players[target_name].is_critical:
                self.players[target_name].charges = 0

            else:
                # handle sawed gun
                damage = 2 if self.round.gun_is_sawed else 1
                self.round.gun_is_sawed = False

                self.players[target_name].charges -= damage

                if self.players[target_name].charges <= self.critical_charges:
                    self.players[target_name].is_critical = True

        self.eject_shell(is_live)
        if not self.round:
            return

        # advance turn
        shooter_name = "player" if self.round.is_players_turn else "dealer"
        if shooter_name != target_name or is_live:
            next_player = "dealer" if self.round.is_players_turn else "player"
            try:
                self.round.handcuffed_player_names.remove(next_player)
            except KeyError:
                self.round.is_players_turn = not self.round.is_players_turn

@dataclass
class GameState:
    player_names: List[str]
    is_double_or_nothing_mode: bool = False
    total_phases: int = 3
    phase: Optional[PhaseState] = None
    num_completed_phases: int = 0
    winner_names_by_phase: List[str] = field(default_factory=list) # just for sanity checking logs
    winner: Optional[str] = None
    max_items: int = 8

    def shoot(self, target_name, is_live):
        self.phase.raw_shoot(target_name, is_live)
        non_target_name = "dealer" if target_name == "player" else "player"
        if self.phase.players[target_name].charges <= 0:

            # the non-target wins the phase
            self.winner_names_by_phase.append(non_target_name)
            self.num_completed_phases += 1
            self.phase = None

            # the non-target wins the game if:
            if (
                # the human player dies in double-or-nothing mode
                (target_name == "player" and self.is_double_or_nothing_mode)

                # or the target dies in the last phase
                or (self.num_completed_phases == self.total_phases)
            ):
                self.winner = non_target_name
            return
