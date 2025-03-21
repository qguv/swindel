#!/usr/bin/env python3

from argparse import ArgumentParser, FileType
from collections import OrderedDict
from copy import deepcopy
import sys

from exceptions import GameError, TurnError
from game_state import GameState, PhaseState, Player, RoundState
from items import Items

cardinal_to_ordinal = {
    "second": 1,
    "third": 2,
    "fourth": 3,
    "fifth": 4,
    "sixth": 5,
    "seventh": 6,
    "eighth": 7,
}

items_by_name = {
    "beer": Items.BEER,
    "cigs": Items.CIGARETTES,
    "cuffs": Items.HANDCUFFS,
    "glass": Items.MAGNIFYING_GLASS,
    "knife": Items.HAND_SAW,
    "phone": Items.BURNER_PHONE,
}

story_mode_items = set([
    Items.BEER,
    Items.CIGARETTES,
    Items.HAND_SAW,
    Items.HANDCUFFS,
    Items.MAGNIFYING_GLASS,
])

double_or_nothing_items = set([
    Items.ADRENALINE,
    Items.BEER,
    Items.BURNER_PHONE,
    Items.CIGARETTES,
    Items.EXPIRED_MEDICINE,
    Items.HAND_SAW,
    Items.HANDCUFFS,
    Items.INVERTER,
    Items.MAGNIFYING_GLASS,
])

multiplayer_items = set([
    Items.ADRENALINE,
    Items.BEER,
    Items.BURNER_PHONE,
    Items.CIGARETTES,
    Items.HAND_SAW,
    Items.INVERTER,
    Items.JAMMER,
    Items.MAGNIFYING_GLASS,
    Items.REMOTE,
])


class LogParseError(Exception):
    '''exited without validating the entire log'''


class NoSuchPlayer(LogParseError):
    '''log refers to a nonexistent player'''
    def __init__(self, player_name, *args, **kwargs):
        msg = f"no such player {player_name}"
        super().__init__(msg, *args, **kwargs)


class WrongPhase(LogParseError):
    '''log refers to a nonexistent player'''
    def __init__(self, phase_name, *args, **kwargs):
        msg = f"expected a round in phase {phase_name}"
        super().__init__(msg, *args, **kwargs)


class NoMatch(LogParseError):
    '''line didn't match any known pattern'''


class SetupError(LogParseError):
    '''couldn't start the game because setup was incomplete'''


class CheckFailed(LogParseError):
    '''!check line failed'''


def parse_line(state: GameState, line):
    line = line.strip()

    # ignore comments
    if line.startswith("#"):
        return state

    # separate lines conjoined by a semicolon
    conjoined_lines = line.split(";")
    if len(conjoined_lines) > 1:
        for conjoined_line in conjoined_lines:
            state = parse_line(state, conjoined_line)
        return state

    if not line:
        return state

    # treat commas, dots, and equals signs as separate words
    for c in ',.=':
        line = line.replace(c, f" {c} ")

    words = line.split()

    try:
        check_query_line(state, words)
        return state
    except NoMatch:
        pass

    # TODO: handle repeated games in double-or-nothing mode
    if state.winner is not None:
        raise SetupError("game over")

    if state.phase is None:
        # TODO: maybe give context that we can only accept phase setup commands?
        return parse_game_setup_line(state, words)

    if state.phase.round is None:
        # TODO: maybe give context that we can only accept round setup commands?
        return parse_round_setup_line(state, words)

    if (words[0] == "dealer") == state.phase.round.is_players_turn:
        raise TurnError()

    return parse_game_line(state, words)


def parse_game_setup_line(old_state: GameState, words) -> GameState:
    new_state = deepcopy(old_state)
    match words:

        case ["player", "uses", "pills"]:
            new_state.is_double_or_nothing_mode = True

        case ["phase", phase_name, ",", _max_charges, "charges", *more] | ["phase", phase_name, ",", _max_charges, "charge", *more]:
            # phase in log: one-indexed tally numerals
            # phase_num here: zero-indexed int
            expected_phase_name = "I" * (new_state.num_completed_phases + 1)
            expected_phase_num = new_state.num_completed_phases

            phase_num = len(phase_name) - 1
            if new_state.num_completed_phases != phase_num:
                raise SetupError(f"expected phase {expected_phase_name}")

            max_charges = int(_max_charges)
            players = OrderedDict(
                (player_name, Player(charges=max_charges))
                for player_name in new_state.player_names
            )

            match more:
                case []:
                    new_state.phase = PhaseState(
                        players=players,
                        max_charges=max_charges,
                    )
                case [",", "critical", "at", _critical_charges]:
                    critical_charges = int(_critical_charges)
                    new_state.phase = PhaseState(
                        players=players,
                        max_charges=max_charges,
                        critical_charges=critical_charges,
                    )
                case _:
                    raise NoMatch(f"expecting: phase {expected_phase_num}, {{{{int}}}} charges, critical at {{{{int}}}}")

        case _:
            expected_phase_num = new_state.num_completed_phases
            raise NoMatch(f"expecting: phase {expected_phase_num}, {{{{int}}}} charges")
    return new_state

def parse_round_setup_line(old_state: GameState, words) -> GameState:
    new_state = deepcopy(old_state)
    match words:

        # just for decoration
        # TODO: make this a check
        case ["round", _phase_num, ".", _round_num]:
            phase_num = len(_phase_num) - 1
            if phase_num != new_state.num_completed_phases:
                raise SetupError(f"expected a round in phase {"I" * (new_state.num_completed_phases + 1)}")
            round_num = int(_round_num) - 1
            if round_num != new_state.phase.num_completed_rounds:
                raise SetupError(f"expected round {new_state.phase.num_completed_rounds + 1}")

        case [player_name, "gets", *separated_item_names]:
            # future TODO check that all players got the same number of new items _this round_

            # skip separators (odd-numbered elements)
            item_names = separated_item_names[::2]

            items = [items_by_name[item_name.strip()] for item_name in item_names]
            new_state.phase.players[player_name].items.extend(items)
            if len(new_state.phase.players[player_name].items) > new_state.max_items:
                raise GameError(f"{player_name} has too many items")

        # this line actually starts the round
        case ["dealer", "loads", _total_live_shells, "live", ",", _total_blank_shells, "blank"]:
            total_live_shells = int(_total_live_shells)
            total_blank_shells = int(_total_blank_shells)
            if total_live_shells + total_blank_shells > 8:
                raise GameError("too many shells in the chamber! max 8 per round")
            if 0 in (total_live_shells, total_blank_shells):
                raise GameError("there must be at least one live and one blank shell per round")
            new_state.phase.round = RoundState(
                total_live_shells=total_live_shells,
                total_blank_shells=total_blank_shells,
            )

        case _:
            raise NoMatch("expecting round setup line")
    return new_state

def check_query_line(state: GameState, words) -> None:
    match words:

        case ["!check", player_name, "odds"]:
            print(player_name, "odds:", state.phase.win_probability(player_name))

        case ["!check", expected_winner_name, "charges", "=", _expected_value]:
            expected_value = int(_expected_value)
            if state.phase is None:
                if expected_value != 0:
                    raise CheckFailed(f"actually, {expected_winner_name} has 0 charges because no phase is in progress (yet/anymore)")
                return
            if expected_winner_name not in state.phase.players:
                raise NoSuchPlayer(expected_winner_name)
            player_charges = state.phase.players[expected_winner_name].charges
            if player_charges != int(expected_value):
                raise CheckFailed(f"actually, {expected_winner_name} has {player_charges} charges")

        case ["!check", expected_winner_name, "charges", "=", _expected_value]:
            expected_value = int(_expected_value)
            if state.phase is None:
                if expected_value != 0:
                    raise CheckFailed(f"actually, {expected_winner_name} has 0 charges because no phase is in progress (yet/anymore)")
                return
            if expected_winner_name not in state.phase.players:
                raise NoSuchPlayer(expected_winner_name)
            player_charges = state.phase.players[expected_winner_name].charges
            if player_charges != int(expected_value):
                raise CheckFailed(f"actually, {expected_winner_name} has {player_charges} charges")

        case ["!check", expected_winner_name, "items", "=", *_separated_expected_item_names]:

            # skip separators (odd-numbered elements)
            _expected_item_names = _separated_expected_item_names[::2]
            expected_items = sorted(items_by_name[name.strip()] for name in _expected_item_names)

            if state.phase is None and len(expected_items) != 0:
                raise CheckFailed(f"actually, {expected_winner_name} has no items because no phase is in progress (yet/anymore)")

            items = sorted(state.phase.players[expected_winner_name].items)
            if items != expected_items:
                raise CheckFailed(f"actually, {expected_winner_name} has {items}")

        case ["!check", "shells", "=", _expected_num_live, "live", ",", _expected_num_blank, "blank"]:
            expected_num_live = int(_expected_num_live)
            expected_num_blank = int(_expected_num_blank)
            if state.phase is None or state.phase.round is None:
                if expected_num_live != 0 or expected_num_blank != 0:
                    raise CheckFailed("actually, there are no shells because no round is in progress (yet/anymore)")
                return
            num_live = state.phase.round.remaining_live_shells()
            num_blank = state.phase.round.remaining_blank_shells()
            if num_live != expected_num_live or num_blank != expected_num_blank:
                raise CheckFailed(f"actually, there are {num_live} live, {num_blank} blank shells left")

        case [expected_winner_name, "wins", *more]:
            match more:
                case ["phase", expected_phase_name]:
                    expected_phase_num = len(expected_phase_name) - 1
                    if expected_phase_num != state.num_completed_phases - 1:
                        raise WrongPhase("I" * state.num_completed_phases)
                    winner_name = state.winner_names_by_phase[expected_phase_num]
                    if expected_winner_name != winner_name:
                        raise CheckFailed(f"actually, {winner_name} won phase {expected_phase_name}")

                case ["game"]:
                    if state.winner is None:
                        raise CheckFailed("actually, the game is ongoing")
                    if state.winner != expected_winner_name:
                        raise CheckFailed(f"actually, {state.winner} won the game")

                case _:
                    raise NoMatch("expecting query line")

        case _:
            raise NoMatch("expecting query line")

def parse_game_line(old_state: GameState, words) -> GameState:
    new_state = deepcopy(old_state)
    match words:
        # TODO check that the shell type doesn't clash with a shell we just saw using the glass
        case [player_name, "shoots", target_name, ",", _shell_type]:

            # parse line
            if target_name == "self":
                target_name = player_name
            is_live = _shell_type == "live"

            new_state.shoot(target_name, is_live)

        case [player_name, "uses", item_name, *_]:
            item = items_by_name[item_name]
            try:
                new_state.phase.players[player_name].items.remove(item)
            except ValueError as e:
                raise GameError(f"{player_name} doesn't have {item_name}") from e

            match words:

                case [player_name, "uses", "cigs"]:
                    if not new_state.phase.players[player_name].is_critical:
                        new_state.phase.players[player_name].charges = min(
                            new_state.phase.max_charges,
                            new_state.phase.players[player_name].charges + 1,
                        )

                case [player_name, "uses", "phone"]:
                    if player_name == "player":
                        raise LogParseError("missing information: what did the player see?")
                    # TODO: something epistemic

                case [player_name, "uses", "phone", ",", "hears", _shell_cardinal, _shell_type]:
                    is_live = _shell_type == "live"
                    try:
                        shells_from_now = cardinal_to_ordinal[_shell_cardinal]
                    except KeyError as e:
                        raise LogParseError("unknown cardinal (use 'second', 'third', etc.)") from e
                    if player_name != "player":
                        raise LogParseError("too much information: we shouldn't know what they see")
                    new_state.phase.round.learn_future_shell(shells_from_now, is_live)

                case [player_name, "uses", "knife"]:
                    new_state.phase.round.gun_is_sawed = True

                case [player_name, "uses", "cuffs"]:
                    other_player = "dealer" if player_name == "player" else "player"
                    new_state.phase.round.handcuffed_player_names.add(other_player)

                case [player_name, "uses", "glass"]:
                    if player_name == "player":
                        raise LogParseError("missing information: what did the player see?")
                    # TODO: something epistemic

                case [player_name, "uses", "glass", ",", "sees", _shell_type]:
                    if player_name != "player":
                        raise LogParseError("too much information: we shouldn't know what they see")
                    is_live = _shell_type == "live"
                    new_state.phase.round.learn_future_shell(0, is_live)

                case [player_name, "uses", "beer", ",", "ejects", _shell_type]:
                    is_live = _shell_type == "live"
                    new_state.phase.eject_shell(is_live)

                case _:
                    raise NoMatch("expecting game line")

        case _:
            raise NoMatch("expecting game line")

    return new_state


def parse_logfile(f):
    game_state = GameState(player_names=["player", "dealer"])
    for i, line in enumerate(f):
        try:
            game_state = parse_line(game_state, line)
        except Exception as e:
            print(f"{f.name} failed", file=sys.stderr)
            print("line", i+1, file=sys.stderr)
            print(line.strip(), file=sys.stderr)
            if isinstance(e, (LogParseError, GameError)):
                print(e, file=sys.stderr)
                return
            raise e
    print(f"{f.name} ok", file=sys.stderr)
    return game_state


def parse_args():
    parser = ArgumentParser()
    parser.add_argument("LOGFILE", nargs="+", type=FileType('r'))
    return parser.parse_args()


def main(args):
    for logfile in args.LOGFILE:
        game = parse_logfile(logfile)
        if not game:
            sys.exit(1)


if __name__ == "__main__":
    main(parse_args())
