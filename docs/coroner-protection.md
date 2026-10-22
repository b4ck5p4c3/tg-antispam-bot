# Coroner protection

Coroner has one reference account. Confirmed deletion candidates enter a persisted,
user-wide quarantine before any removal. The default delay is 60 minutes. A candidate
stores a global membership generation and its target chat IDs, so a stale removal
cannot apply to a later rejoin. Profile checks have one schedule and queue job per
user; successful confirmation creates removal targets for every known chat. Accounts are shown as inline URL buttons using
`tg://user?id=...`; tapping one opens that account directly, without an intermediate
bot card or selection step. Telegram can reject these buttons because of account privacy
restrictions, especially in private chats. A rejected keyboard is split into groups
until the individual restricted account buttons are identified. Allowed buttons stay
available; only individually rejected IDs are listed as unavailable and formatted for
copying. The probes edit the same message in the background, share the module RPM budget,
and leave moderation, Stop and navigation responsive. A newer view cancels the old probes.
Rejections are cached per recipient chat in memory for `account_link_retry_seconds`
(default 300); **Update** explicitly retries the current page. Expected privacy refusals
do not fill the module error list; other API failures are still recorded.
See [Telegram's linking restrictions](https://core.telegram.org/bots/api#inlinekeyboardbutton).

## Rules and initial thresholds

- New candidates: count unique users detected today per grade; compare with the mean
  of the previous seven complete calendar days, excluding today. Trigger at
  `max(minimum users, ceil(multiplier * mean))`. Every grade starts with multiplier
  3 and minimum 5. A user's first candidate event in a calendar day is counted once;
  its detection grade is fixed for historical comparison. The user's current global
  grade continues to advance normally and is shown separately.
- Deleted profiles: at least 20 unique users with a determinate result in 30 minutes;
  trigger at 80% false results. Evaluated globally and per moderated chat. Latest
  determinate results deduplicate users across repeated checks and chats. Reference
  lookups and secondary profile confirmations do not increase this trigger sample.
- Recently alive transitions: in 30 minutes, at least 20 recently alive checked users,
  at least 5 negative matches, and a 50% negative ratio. Recently alive means a
  successful check or actual new message within the previous 24 hours.
- Incomplete/contradictory profiles: at least 20 unique users in 30 minutes, at least
  3 indeterminate profiles, and a 20% indeterminate ratio. These results never count
  as confirmed deletions.
- Candidate activity: the first actual new message sent by a candidate after detection
  cancels that candidate, starts its cooldown, and blocks all automatic quarantine
  releases. A new contradiction revokes approval for the activity rule immediately.
  Forwarded attribution, service join messages and edits of older messages do not
  provide this activity evidence.

All thresholds and windows below are editable. A rule with too few observations is
explicitly labelled disabled for insufficient data. Missing calendar-day coverage is
not treated as zero candidates. Only observed zero days contribute a zero to the mean.
Coverage is accumulated while checks are running, with configurable tolerance for
maintenance gaps and a configurable required daily coverage percentage (default 100%).
Restart gaps and stopped periods remain missing coverage. Changing calendar timezone
invalidates calendar comparison data and metric rollups, without resetting quarantine,
removal budgets or incidents.

## Manual review and notifications

An unapproved anomaly creates a module-wide removal block until it normalizes or is approved. The module may still report `running`:
ordinary checks and observation continue; **Protection: blocked** reports the independent
removal gate. `/coroner stop` still stops all profile checks, including approved work.
A reference failure separately puts the module in `error` and requires a successful
manual start. Restart preserves both protection and the saved module status. A running
module checks the reference again before resuming its queue; stopped and error states
require a manual start. The first launch defaults to stopped.

Existing `/as_service` subscribers are notified only after rechecking their administrator
rights in every moderated chat. The module edits its existing review notification at the
configured interval. Every notification, authorization lookup and UI operation shares
Coroner's Telegram RPM budget. Failed notification delivery does not release protection.

`/coroner review` and service notifications show the current quarantine statistics and
account buttons together. Quarantine pages show only the count, page number and account
buttons. IDs are labels, arranged in three columns by default. Pages fill the configured
100-button budget after reserving controls and Previous/Next buttons.
`account_links_per_page` and `account_links_per_row` control density.

**Confirm all accounts** is always available, including when the quarantine is empty.
It approves the anomaly parameters currently exceeded, rather than a saved list of users.
New candidates are covered while the same rules remain continuously triggered. Each
permission is removed as soon as its parameter normalizes or its sample becomes
insufficient. Another breach of that rule requires confirmation again. An unrelated
newly triggered rule blocks removals independently; it does not revoke permission for
rules that remain continuously exceeded. Changing a rule's window, threshold or minimum
sample also requires new confirmation. Approvals persist across restarts while their
conditions remain active; there is no fixed approval lifetime.

There are no review snapshots, per-account approvals, selections or partial decisions.
Review always shows the live quarantine. **Stop Coroner** stops all checks until a manual
start; confirmation never starts a stopped or emergency-stopped module, shortens quarantine,
or skips reference/member-count checks and removal budgets. Percentage budgets have their
own explicit two-hour bypass, described below. Old snapshot navigation opens the live
review; an old Confirm button approves the currently triggered anomaly rules. Historical
account approvals are discarded on upgrade rather than expanded to module-wide permission.
Subscriber notification messages are reused.

Normalized detector reasons are removed from current status, so a historical peak is not
shown as a current breach. Temporary error history and historical detector statistics are
preserved. Candidates confirmed alive return to ordinary monitoring with a configurable
cooldown against immediate recreation. `/coroner acknowledge` can release remaining
non-detector incidents after the quarantine is empty; it preserves removal budget evidence.
Safety gates are rechecked immediately before issuing a removal. An already-issued
Telegram request may still complete after a block; its reservation remains charged.

## Persisted removal budgets

Each rolling window enforces a per-chat and a global percentage limit. There are no
fixed removal-count caps. A single user banned from three chats consumes three units.
The effective allowance is `floor(population * percent / 100)`. There is no rounding
upward for small chats: 5% of 10 members permits zero removals.

Initial limits are 5% per chat and globally in 10 minutes, and 10% per chat and globally
in 24 hours. Adjust these percentages for the intended chat populations. The retired
`chat_count` and `global_count` configuration fields are discarded automatically. Legacy
quota incidents stored as absolute counts are retired, and the current percentage
rules are enforced again before the next removal. Other incidents remain in place.
Global population sums chat memberships. Counts are fetched through the shared RPM
budget and cached for the configured lifetime. The minimum observed population among
current counts and active reservations supplies the percentage denominator, preventing
growth in the reported population from inflating an already active budget.

The module atomically saves a reservation before attempting removal. Pending requests
consume budget even if they wait longer than the window. A successful or uncertain
request is charged conservatively from the time its outcome is received. A definite
Telegram rejection or a guard cancellation before dispatch releases the reservation.
A lost response remains charged and creates an incident; a pending reservation found
after restart becomes uncertain and is charged from recovery time. Member-count failure
blocks removal. Anomaly approval does not bypass percentage limits.

Administrators can enable a module-wide bypass with `/coroner bypass`, or **Bypass
removal limits** when a quota incident exists. The configured duration defaults to
7200 seconds (`removal_limit_bypass_seconds`). `/coroner bypass stop` and **Cancel limit
bypass** restore percentage enforcement early. Repeating the enable command while
active does not extend its deadline. The deadline and administrator ID persist in JSON,
so restarting the bot does not reset the timer. Status, review and detector views show
the remaining duration. The bypass does not start a stopped module.

While active, the bypass ignores only percentage quota checks and quota-only removal
blocks. Other anomaly incidents still require approval; quarantine, reference checks,
member-count verification, retained-history checks and uncertain-removal protection
remain active. Reservations continue to accumulate during bypass and are checked again
immediately before dispatch. Expiry or cancellation therefore restores enforcement
without discarding any usage. A quota reason clears once the rolling budget permits the next removal again; fresh
member counts and all budget rules are still checked before dispatch. Expiry restores
any quota block whose usage remains over the limit.

Reservations are retained for at least the configured retention, removal statistics
period and longest budget window. If a later configuration extends a window into a
period whose reservation data was discarded, automatic removals block for insufficient
budget history. Budget evidence is never replaced with invented zero counts.

Dry run uses the same quarantine, checks, incidents and virtual reservations, and logs
intended permanent bans. It sends no ban requests and adds no actual removal-history entries.
Virtual reservations constrain dry runs; switching to real mode does not charge virtual
operations against the actual budget.

## Statistics

`/coroner` and its Update button show the module-wide summary in private chats or
moderated groups. Queued checks exclude quarantined users, including their waiting time;
quarantine size is displayed separately. Detectors, Quarantine and Review removals open dedicated pages.
All commands and buttons require current administrator rights in every moderated chat.

Detector pages show settings, sample availability, current check counts, raw false and
unknown counts, deduplicated trigger samples, percentages, effective thresholds and
progress toward triggering. Candidate rules show current quarantine occupancy and new
daily candidates separately. An insufficient sample disables that rule explicitly;
other rules and mandatory removal limits continue to apply.

Minimum, maximum and mean are calculated over recorded metric samples in the configured
number of calendar days including today. Percentage means also report the weighted
`sum(matches) / sum(samples)`. Sampling interval is configurable. Daily compact rollups
retain ranges and sums rather than every historical point. Missing percentage samples
are excluded instead of becoming zeros. Changing a rule's window prevents comparisons
against observations recorded for a different window.
Incident trigger values are captured immediately. Views include the live current
observation in the displayed ranges without changing historical storage.

Additional pages show quarantine readiness and oldest age, cancellations confirmed
alive, live-message settings, anomaly permissions and cooldown, budgets and their usage,
and removals for the configured statistics period (7 days by default). Removal
statistics show unique user counts plus chat-removal counts; percentages use current
summed chat memberships. The existing 30-day module totals remain available.

Quarantine, anomaly permissions, detector observations, calendar coverage, budget evidence
and protection reasons live in `coroner_state.sqlite3`. Human-readable temporary errors remain
in memory only, at most five for seven days. Latched reasons are separate protection
state. Current detector reasons are removed after normalization; temporary error expiry
does not clear unresolved protection conditions.

## Configuration

The following `protection` object is added automatically to valid existing
`coroner_config.json` files. Edit settings while stopped, then start to reload.
Legacy `api_errors` settings are discarded automatically. The removed API failure
detector no longer collects metrics or blocks removals. Existing blocks caused solely
by that detector are cleared on startup; blocks from other causes are preserved.
Existing candidate deadlines retain the values assigned when created. Obsolete review
snapshots, per-account grants and the `approval_seconds` / `resolved_request_retention_days`
configuration settings are removed automatically.

```json
{
  "protection": {
    "quarantine_seconds": 3600,
    "recheck_seconds": 300,
    "removal_limit_bypass_seconds": 7200,
    "rejection_cooldown_seconds": 86400,
    "candidate_history_days": 7,
    "candidate_coefficients": {
      "G1": 3.0,
      "G2": 3.0,
      "G3": 3.0,
      "G4": 3.0
    },
    "candidate_minimum_users": {
      "G1": 5,
      "G2": 5,
      "G3": 5,
      "G4": 5
    },
    "day_timezone": "UTC",
    "minimum_day_coverage_percent": 100,
    "maximum_collection_gap_seconds": 30,
    "false_results": {
      "window_seconds": 1800,
      "minimum_users": 20,
      "minimum_matches": 1,
      "threshold_percent": 80
    },
    "recent_alive_seconds": 86400,
    "alive_transitions": {
      "window_seconds": 1800,
      "minimum_users": 20,
      "minimum_matches": 5,
      "threshold_percent": 50.0
    },
    "profile_inconsistencies": {
      "window_seconds": 1800,
      "minimum_users": 20,
      "minimum_matches": 3,
      "threshold_percent": 20.0
    },
    "activity_minimum_users": 1,
    "activity_window_seconds": 1800,
    "metric_sample_seconds": 300,
    "metric_history_days": 7,
    "removal_statistics_days": 7,
    "notification_interval_seconds": 300,
    "member_count_cache_seconds": 60,
    "account_links_per_page": 100,
    "account_links_per_row": 3,
    "account_link_retry_seconds": 300,
    "detector_page_size": 3,
    "reservation_retention_days": 30,
    "removal_limits": [
      {
        "name": "short",
        "window_seconds": 600,
        "chat_percent": 5.0,
        "global_percent": 5.0
      },
      {
        "name": "daily",
        "window_seconds": 86400,
        "chat_percent": 10.0,
        "global_percent": 10.0
      }
    ]
  }
}
```
