from collections import OrderedDict, defaultdict
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from exceptions import GameError
from items import Items

# true is live, false is blank
type ShellType = bool
LIVE_SHELL = True
BLANK_SHELL = False
ANY_SHELL = None

@dataclass
class RoundState:
    total_live_shells: int
    total_blank_shells: int
    past_shells: List[ShellType] = field(default_factory=list)
    is_players_turn: bool = True
    gun_is_sawed: bool = False
    handcuffed_player_names: Set[str] = field(default_factory=set)
    known_shells: Dict[int, ShellType] = field(default_factory=dict)
    dealer_known_shells_theories: List[Dict[int, ShellType]] = field(default_factory=list)

    def current_player_name(self, _reverse=False) -> str:
        return "player" if (self.is_players_turn != _reverse) else "dealer"

    def current_opponent_name(self) -> str:
        return self.current_player_name(_reverse=True)

    def remaining_shells(self, *, of_type=ANY_SHELL) -> int:
        if of_type is None:
            return self.total_shells() - len(self.past_shells)
        return (
            self.total_shells(of_type=of_type)
            - sum(1 for past_shell_type in self.past_shells if past_shell_type == of_type)
        )

    def remaining_known_shells(self, *, of_type=ANY_SHELL) -> int:
        return sum(1 for i, known_shell_is_live in self.known_shells.items() if (of_type is ANY_SHELL or of_type == known_shell_is_live) and i >= len(self.past_shells))

    def remaining_unknown_shells(self, *, of_type=ANY_SHELL) -> int:
        return self.remaining_shells(of_type=of_type) - self.remaining_known_shells(of_type=of_type)

    def total_shells(self, *, of_type=ANY_SHELL) -> int:
        if of_type is ANY_SHELL:
            return self.total_live_shells + self.total_blank_shells
        return self.total_live_shells if of_type else self.total_blank_shells

    def learn_future_shell(self, shells_from_now, is_live):
        self.assert_future_shell(shells_from_now, is_live)
        i = len(self.past_shells) + shells_from_now
        self.known_shells[i] = is_live

        # if the information we learn contradicts any dealer known_shells theories, we can eliminate those
        num_theories_before = len(self.dealer_known_shells_theories)
        self.dealer_known_shells_theories = [t for t in self.dealer_known_shells_theories if t.get(i, is_live) == is_live ]
        num_theories_eliminated = len(self.dealer_known_shells_theories) - num_theories_before
        if num_theories_eliminated:
            print("eliminated", num_theories_eliminated, "theories about the dealer's knowledge!", len(self.dealer_known_shells_theories), "remaining") # DEBUG

    def assert_future_shell(self, shells_from_now, is_live):

        # are there enough shells?
        i = len(self.past_shells) + shells_from_now
        if i >= self.total_shells():
            raise GameError("actually, there aren't enough shells for that!")

        # does it contradict with something we can deduce based on public knowledge of past shells?
        if self.remaining_shells(of_type=is_live) < 1:
            raise GameError(f"actually, there are no {"live" if is_live else "blank"} shells left")

        # does it contradict with something we learned
        try:
            known_shell_is_live = self.known_shells[i]

        # here, we don't know anything about this shell...
        # but does the new information contradict with something we can deduce based on current knowledge of future shells?
        except KeyError as e:
            if self.remaining_unknown_shells(of_type=is_live) < 1:
                raise GameError(f"actually, all {"live" if is_live else "blank"} shells are accounted for") from e

        # here, we know what the shell is, just check that it's right
        else:
            if known_shell_is_live != is_live:
                raise GameError(f"actually, player knows this shell to be {"live" if known_shell_is_live else "blank"}")

    def chance_shell_is_live(self):

        # are there enough shells?
        i = len(self.past_shells)
        if i >= self.total_shells():
            raise GameError("actually, there are no shells left to shoot!")

        # have we already learned it?
        try:
            return 1.0 if self.known_shells[i] else 0.0

        # does it contradict with something we can deduce based on shell count
        except KeyError:
            return self.remaining_unknown_shells(of_type=LIVE_SHELL) / self.remaining_unknown_shells()


    def raw_eject_shell(self, is_live):
        self.assert_future_shell(0, is_live)

        # if the information we see contradicts any dealer known_shells theories, we can eliminate those
        i = len(self.past_shells)
        num_theories_before = len(self.dealer_known_shells_theories)
        self.dealer_known_shells_theories = [t for t in self.dealer_known_shells_theories if t.get(i, is_live) == is_live ]
        num_theories_eliminated = len(self.dealer_known_shells_theories) - num_theories_before
        if num_theories_eliminated:
            print("eliminated", num_theories_eliminated, "theories about the dealer's knowledge!", len(self.dealer_known_shells_theories), "remaining") # DEBUG

        self.past_shells.append(is_live)

@dataclass
class Player:
    charges: int
    items: List[Items] = field(default_factory=list)
    is_critical: bool = False

def player_preference(chances: Tuple[float, float, float]):
    '''player prefers a player win, otherwise a draw'''
    return (chances[0], chances[1])

def dealer_preference(chances: Tuple[float, float, float]):
    '''dealer prefers a dealer win, otherwise a draw'''
    return (chances[2], chances[1])

def about_equal(xs, e=0.0001):
    xs = iter(xs)
    x0 = next(xs)
    for x in xs:
        if abs(x - x0) > e:
            return False
    return True

def elements_about_equal(ts, **kwargs):
    ts = iter(ts)
    t0 = next(ts)
    for t in ts:
        for nth_elements in zip(t0, t):
            if not about_equal(nth_elements, **kwargs):
                return False
    return True


def elementwise_sum(ts):
    return tuple(
        sum(nth_elements)
        for nth_elements in zip(*ts)
    )


def scalar_mul(a, xs):
    return tuple(a * x for x in xs)


def dmap(d, f):
    return { k: f(v) for k, v in d.items() }

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

    def best_move(self, depth=1) -> Tuple[str | None, Tuple[float, float, float]]:
        # FIXME: update to account for current theories of dealer's knowledge
        if self.players["dealer"].charges <= 0:
            print("\t" * depth, "player wins") # DEBUG
            return (None, (1.0, 0.0, 0.0))
        if self.players["player"].charges <= 0:
            print("\t" * depth, "dealer wins") # DEBUG
            return (None, (0.0, 0.0, 1.0))
        if self.round is None:
            print("\t" * depth, "it's a tie") # DEBUG
            return (None, (0.0, 1.0, 0.0))

        live_chance = self.round.chance_shell_is_live()
        blank_chance = 1.0 - live_chance

        player_name = self.round.current_player_name()
        opponent_name = self.round.current_opponent_name()

        chances_after_shooting = defaultdict(list)
        for target_name in ("dealer", "player"):
            print("\t" * depth, f"if {player_name} shot {"self" if target_name == player_name else target_name}...")
            for is_live, chance in ((True, live_chance), (False, blank_chance)):
                result = deepcopy(self)
                try:
                    result.raw_shoot(target_name, is_live)
                except GameError as e:
                    print("\t" * (depth+1), f"(the shell can't be {"live" if is_live else "blank"} because {e})")
                else:
                    print("\t" * (depth+1), f"...and the shell were {"live" if is_live else "blank"}, then:")
                    sub = result.best_move(depth=depth+2)[1]
                    print("\t" * (depth+2), sub)
                    chances_after_shooting[target_name].append(
                        tuple(chance * x for x in sub)
                    )
            chances_after_shooting[target_name] = tuple(map(sum, zip(*chances_after_shooting[target_name])))
            print("\t" * (depth+1), chances_after_shooting[target_name])

        preference_after_shooting = dmap(chances_after_shooting, player_preference if self.round.is_players_turn else dealer_preference)

        if elements_about_equal(list(preference_after_shooting.values())):
            print("\t" * depth, "so", player_name, "shoots anyone, expecting", chances_after_shooting[opponent_name])
            return (
                "either",
                elementwise_sum((
                    scalar_mul(0.5, chances_after_shooting[player_name]),
                    scalar_mul(0.5, chances_after_shooting[opponent_name]),
                )),
            )
        if preference_after_shooting[player_name] > preference_after_shooting[opponent_name]:
            print("\t" * depth, "so", player_name, "shoots self expecting", chances_after_shooting[player_name], "vs otherwise", chances_after_shooting[opponent_name])
            return (player_name, chances_after_shooting[player_name])
        print("\t" * depth, "so", player_name, "shoots", opponent_name, "expecting", chances_after_shooting[opponent_name], "vs otherwise", chances_after_shooting[player_name])
        return (opponent_name, chances_after_shooting[opponent_name])

    def raw_shoot(self, target_name, is_live):

        # FIXME compare against theories

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
