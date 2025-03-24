from collections import OrderedDict, defaultdict
from copy import deepcopy
from dataclasses import dataclass, field
import sys

from exceptions import GameError
from items import Items
from util import about_equal, all_about_equal_elementwise, elementwise_sum, remove_unless, scalar_mul

# true is live, false is blank
type ShellType = bool
LIVE_SHELL = True
BLANK_SHELL = False
ANY_SHELL = None

type KnownShells = dict[int, ShellType]
type PlayerName = str
type PlayerWinChance = float
type TieChance = float
type DealerWinChance = float
type Chances = tuple[float, float, float]

@dataclass
class RoundState:
    total_live_shells: int
    total_blank_shells: int
    past_shells: list[ShellType] = field(default_factory=list)
    is_players_turn: bool = True
    gun_is_sawed: bool = False
    handcuffed_player_names: set[str] = field(default_factory=set)
    known_shells: KnownShells = field(default_factory=dict)
    dealer_known_shells_theories: list[KnownShells] = field(default_factory=lambda: [{}])

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
        self.eliminate_dealer_known_shells_theories_contradictions(i, is_live)

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
        turn_i = len(self.past_shells)
        self.eliminate_dealer_known_shells_theories_contradictions(turn_i, is_live)
        self.past_shells.append(is_live)


    def eliminate_dealer_known_shells_theories_contradictions(self, turn_i: int, shell_type: ShellType):
        '''once we learn that a particular round is/was loaded for a turn, we can eliminate theories that contradict this'''
        # FIXME: also call this when we can deduce a future round with certainty by counting rounds
        num_theories_before = len(self.dealer_known_shells_theories)
        num_theories_after = remove_unless(self.dealer_known_shells_theories, lambda t: t.get(turn_i, shell_type) == shell_type)
        num_theories_eliminated = num_theories_after - num_theories_before
        if num_theories_eliminated:
            print("eliminated", num_theories_eliminated, "theories about the dealer's knowledge!", num_theories_after, "remaining") # DEBUG
        # maybe glean information from this
        self.maybe_leak_dealer_info()


    def theorize_dealer_phone(self):
        old_theories = self.dealer_known_shells_theories
        self.dealer_known_shells_theories = []

        # suppose the dealer learned about the shell loaded for the future turn with index: suppose_learn_turn_i
        next_turn_i = len(self.known_shells) + 1
        for suppose_learn_turn_i in range(next_turn_i, self.total_shells()):

            new_theories = []
            try:
                known_shell = self.known_shells[suppose_learn_turn_i]
            except KeyError:
                # if we don't know which shell is loaded for the next turn, we have to consider both possibilities
                new_theories.extend({suppose_learn_turn_i: suppose_shell_type} for suppose_shell_type in (LIVE_SHELL, BLANK_SHELL))
            else:
                # if we already know which shell is loaded for this future turn, then that's the only new theory
                new_theories.append({suppose_learn_turn_i: known_shell})

            # add updated versions of the old theories
            self.dealer_known_shells_theories.extend(old_theory | new_theory for new_theory in new_theories for old_theory in old_theories)

        self.maybe_leak_dealer_info()


    def maybe_leak_dealer_info(self):
        '''if we've successfully deduced what the dealer learned, then add this to our knowledge too'''

        for turn_i in range(self.total_shells()):
            for shell_type in (LIVE_SHELL, BLANK_SHELL):
                if self.dealer_knows_that(turn_i, shell_type):
                    print(f"HEY! we deduced that the dealer learned that the {turn_i}th shell is {'live' if shell_type else 'blank'}!")
                    self.known_shells[turn_i] = shell_type
                    sys.exit() # DEBUG


    def dealer_knows_that(self, turn_i: int, shell_type: ShellType) -> bool:
        '''whether we have deduced that the dealer knows that the shell for turn_i is of type shell_type'''
        for theory in self.dealer_known_shells_theories:

            try:
                known_shell_type = theory[turn_i]
            except KeyError:
                # there is at least one case where the dealer doesn't know what this shell is
                return False

            if known_shell_type != shell_type:
                # there is at least one case where the dealer knows that this shell isn't this type
                return False

        return True


@dataclass
class Player:
    charges: int
    items: list[Items] = field(default_factory=list)
    is_critical: bool = False


def player_preference(chances: Chances) -> tuple[float, float]:
    '''player prefers a player win, otherwise a draw'''
    return (chances[0], chances[1])


def dealer_preference(chances: Chances) -> tuple[float, float]:
    '''dealer prefers a dealer win, otherwise a draw'''
    return (chances[2], chances[1])


@dataclass
class PhaseState:
    players: OrderedDict[str, Player]
    max_charges: int
    critical_charges: int = 0
    round: RoundState | None = None
    num_completed_rounds: int = 0

    def eject_shell(self, is_live):
        self.round.raw_eject_shell(is_live)

        # if no shells left, end round
        if len(self.round.past_shells) == self.round.total_shells():
            self.round = None
            self.num_completed_rounds += 1

    def best_move(self, depth=1) -> tuple[PlayerName | None, Chances]:
        '''
        game over? then that's the outcome
        otherwise, for each possible target:
            (
            for each possible shell type:
                in a fork:
                    move
                    then determine the outcome:
                        game over? then that's the outcome
                        same player's turn? then recusively call, that's the outcome
                        other player's turn? then:
                            for each remaining theory of other player's knowledge (or if none, do the following once):
                                in a fork:
                                    clear all theories and dealer_known_shells
                                    set known_shells to the theory
                                    recursively call to get their best choice (ignore the odds they calculate)
                            group the theories based on the dealer's calculated optimal move
                            for each move group:
                                in a fork:
                                    set dealer theories to the ones in the group
                                    make the move on the dealer's behalf
                                    recursively call to get *our* outcome (ignore the best move we chose)
                                multiply the odds by the number of theories in the group
                                return these odds
                            sum the results, that's the outcome
            multiply each outcome by the likelihood of this shell type
            sum the results, that's the outcome
            )
        select the target with the best outcome
        return that target
        '''
        if self.players["dealer"].charges <= 0:
            print("\t" * depth, "player wins") # DEBUG
            return (None, (1.0, 0.0, 0.0))
        if self.players["player"].charges <= 0:
            print("\t" * depth, "dealer wins") # DEBUG
            return (None, (0.0, 0.0, 1.0))
        if self.round is None:
            print("\t" * depth, "it's a tie") # DEBUG
            return (None, (0.0, 1.0, 0.0))

        players = list(self.players.keys())
        prefs = player_preference if self.round.is_players_turn else dealer_preference
        chances_per_target = {target: self._consider_shooting(target, depth=depth) for target in players}
        best_target = (
            None if all_about_equal_elementwise(chances_per_target.values())
            else 'player' if prefs(chances_per_target['player']) > prefs(chances_per_target['dealer'])
            else 'dealer'
        )
        best_chances = chances_per_target[best_target or 'dealer']

        worst_target = "dealer" if best_target == "player" else "player"
        otherwise_msg = [] if best_target is None else ["vs otherwise", chances_per_target[worst_target]]

        player_name = self.round.current_player_name()
        print(
            "\t" * depth,
            "so",
            player_name,
            "shoots",
            (
                "either" if best_target is None
                else "self" if player_name == best_target
                else best_target
            ),
            "expecting",
            best_chances,
            *otherwise_msg,
        )
        return best_target, chances_per_target[best_target]

    def _consider_shooting(self, target_name: PlayerName, *, depth) -> Chances:
        '''
        for each possible shell type:
            (
            in a fork:
                move
                then determine the outcome:
                    game over? then that's the outcome
                    same player's turn? then recusively call, that's the outcome
                    other player's turn? then:
                        for each remaining theory of other player's knowledge (or if none, do the following once):
                            in a fork:
                                clear all theories and dealer_known_shells
                                set known_shells to the theory
                                recursively call to get their best choice (ignore the odds they calculate)
                        group the theories based on the dealer's calculated optimal move
                        for each move group:
                            in a fork:
                                set dealer theories to the ones in the group
                                make the move on the dealer's behalf
                                recursively call to get *our* outcome (ignore the best move we chose)
                            multiply the odds by the number of theories in the group
                            return these odds
                        sum the results, that's the outcome
            )
        multiply each outcome by the likelihood of this shell type
        sum the results, that's the outcome
        '''

        live_chance = self.round.chance_shell_is_live()
        blank_chance = 1.0 - live_chance

        player_name = self.round.current_player_name()

        print("\t" * depth, f"if {player_name} shot {"self" if target_name == player_name else target_name}...")
        return elementwise_sum(
            scalar_mul(chance, self._consider_shooting_with(target_name, shell_type, depth=depth+1))
            for shell_type, chance in ((LIVE_SHELL, live_chance), (BLANK_SHELL, blank_chance))
        )

    def _consider_shooting_with(self, target_name: PlayerName, is_live: ShellType, *, depth) -> Chances:
        '''
        in a fork:
            move
            then determine the outcome:
                game over? then that's the outcome
                same player's turn? then recusively call, that's the outcome
                other player's turn? then:
                    (
                    for each remaining theory of other player's knowledge (or if none, do the following once):
                        in a fork:
                            clear all theories and dealer_known_shells
                            set known_shells to the theory
                            recursively call to get their best choice (ignore the odds they calculate)
                    group the theories based on the dealer's calculated optimal move
                    )
                    for each move group:
                        (
                        in a fork:
                            set dealer theories to the ones in the group
                            make the move on the dealer's behalf
                            recursively call to get *our* outcome (ignore the best move we chose)
                        )
                        multiply the odds by the number of theories in the group
                        return these odds
                    sum the results, that's the outcome
        '''
        result = deepcopy(self)
        try:
            result.raw_shoot(target_name, is_live, eliminate_nonpredictive_theories=False)
        except GameError as e:
            print("\t" * depth, f"(the shell can't be {"live" if is_live else "blank"} because {e})")
        else:
            print("\t" * depth, f"...and the shell were {"live" if is_live else "blank"}, then:")

        if (not result.round) or self.round.is_players_turn == result.round.is_players_turn:
            # either the round is over and we can reuse the base case from the outermost function,
            # or it's the same player's turn and we can just continue reasoning
            _, chances = result.best_move(depth=depth+1)
            print("\t" * depth, chances)
            return chances

        # otherwise, it's the opponent's turn
        theories_by_target = result.theories_by_predicted_target()
        target_weights = calculate_target_weights(theories_by_target)
        return elementwise_sum(
            scalar_mul(
                target_weights[opponent_target],
                result.consider_opponent_shooting(opponent_target, theories, depth=depth),
            )
            for opponent_target, theories in theories_by_target.items()
            if opponent_target is not None # skip these, we've accounted for them in theory_weights
        )

    def consider_opponent_shooting(self, opponent_target, theories, *, depth):
        '''
        in a fork:
            set dealer theories to the ones in the group
            make the move on the dealer's behalf
            recursively call to get *our* outcome (ignore the best move we chose)
        '''
        live_chance = self.round.chance_shell_is_live()
        blank_chance = 1.0 - live_chance

        live_outcome = (0.0, 0.0, 0.0)
        if not about_equal(0.0, live_chance):
            live_case = deepcopy(self)
            live_case.round.dealer_known_shells_theories = theories
            live_case.raw_shoot(opponent_target, LIVE_SHELL, eliminate_nonpredictive_theories=False)
            _, live_outcome = self.best_move(depth)

        blank_outcome = (0.0, 0.0, 0.0)
        if not about_equal(0.0, blank_chance):
            blank_case = deepcopy(self)
            blank_case.round.dealer_known_shells_theories = theories
            blank_case.raw_shoot(opponent_target, BLANK_SHELL, eliminate_nonpredictive_theories=False)
            _, blank_outcome = self.best_move(depth)

        return elementwise_sum((
            scalar_mul(live_chance, live_outcome),
            scalar_mul(blank_chance, blank_outcome),
        ))

    def theories_by_predicted_target(self) -> dict[PlayerName | None, list[KnownShells]]:
        '''
        note: the None key of the return value contains theories that assign
        even chances to both targets. don't forget about these!
        '''
        theories_by_target = defaultdict(list)
        for theory in self.round.dealer_known_shells_theories:
            fork = deepcopy(self)
            fork.round.dealer_known_shells_theories = [{}]
            fork.round.known_shells = theory
            best_target, _ = fork.best_move()
            # warning: this can be None! so check the None key of the result!
            theories_by_target[best_target].append(theory)
        return theories_by_target

    def raw_shoot(self, target_name, is_live, eliminate_nonpredictive_theories=True):

        # check if this is possible given what we know
        self.round.assert_future_shell(0, is_live)

        # eliminate theories which would not have predicted the dealer to have behaved like this
        if eliminate_nonpredictive_theories and not self.round.is_players_turn:
            theories_by_target = self.theories_by_predicted_target()
            self.round.dealer_known_shells_theories = theories_by_target[target_name] + theories_by_target[None]
            if not self.round.dealer_known_shells_theories:
                # return the null theory to maintain the invariant
                self.round.dealer_known_shells_theories.append({})
                print("WARNING: the dealer is not playing optimally, so all bets are off")
                sys.exit() # DEBUG

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
    player_names: list[str]
    is_double_or_nothing_mode: bool = False
    total_phases: int = 3
    phase: PhaseState | None = None
    num_completed_phases: int = 0
    winner_names_by_phase: list[str] = field(default_factory=list) # just for sanity checking logs
    winner: str | None = None
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

def calculate_target_weights(theories_by_target: dict[PlayerName | None, list[KnownShells]]) -> dict[PlayerName, float]:
    n_theories = sum(len(theories) for theories in theories_by_target.values())
    half_of_indifferent_theories = len(theories_by_target[None]) / 2.0
    return {
        target_name: (len(theories) + half_of_indifferent_theories) / n_theories
        for target_name, theories in theories_by_target.items()
        if target_name is not None
    }
