"""Import known chat members while the bot process is shut down."""

import argparse
import os
import time
from pathlib import Path

from src.coroner.CoronerModels import CoronerState, Participant, TrackedUser
from src.coroner.CoronerStore import CoronerStore


def main() -> None:
    data_folder = os.getenv("DATA_FOLDER_PATH") or Path(__file__).parent / "data"
    parser = argparse.ArgumentParser(
        description="Add chat members to Coroner. New users start at G1.",
        epilog="Shut down the bot process first; /coroner stop alone is not enough. "
               "Existing memberships and global ages are preserved. "
               "The chat must be enabled separately with /moderate.",
    )
    parser.add_argument("--chat-id", type=int, required=True, help="Negative Telegram chat ID")
    parser.add_argument("user_ids", type=int, nargs="*", help="Positive Telegram user IDs")
    parser.add_argument("--file", type=Path, help="Text file with IDs separated by whitespace or commas")
    parser.add_argument(
        "--state", type=Path, default=Path(data_folder) / "coroner_state.json",
        help="State file (default: <DATA_FOLDER_PATH>/coroner_state.json)",
    )
    args = parser.parse_args()
    if args.chat_id >= 0:
        parser.error("--chat-id must be a negative Telegram group ID")

    user_ids = set(args.user_ids)
    try:
        if args.file is not None:
            contents = args.file.read_text(encoding="utf-8")
            user_ids.update(int(value) for value in contents.replace(",", " ").split())
        if not user_ids or any(user_id <= 0 for user_id in user_ids):
            parser.error("provide at least one positive user ID")
        state = (CoronerState.model_validate_json(args.state.read_text(encoding="utf-8"))
                 if args.state.exists() else CoronerState())
    except (OSError, ValueError) as error:
        parser.error(str(error))

    # Match the service's migration of older states without a global user registry.
    for chat_id, participants in state.participants.items():
        for user_id, participant in participants.items():
            user = state.users.get(user_id)
            if user is None:
                state.users[user_id] = TrackedUser(since=participant.since, first_chat_id=chat_id)
            elif participant.since < user.since:
                user.since = participant.since
                user.first_chat_id = chat_id

    now = time.time()
    participants = state.participants.setdefault(args.chat_id, {})
    added = new_users = 0
    for user_id in sorted(user_ids):
        if user_id in participants:
            continue
        participants[user_id] = Participant(first_seen_at=now)
        added += 1
        if user_id not in state.users:
            state.users[user_id] = TrackedUser(since=now, first_chat_id=args.chat_id)
            new_users += 1

    try:
        CoronerStore(str(args.state.parent)).save(args.state.name, state.model_dump_json(indent=2))
    except OSError as error:
        parser.error(str(error))
    print(f"Added memberships: {added}; already recorded: {len(user_ids) - added}; "
          f"new users in G1: {new_users}. Saved to {args.state}")


if __name__ == "__main__":
    main()
