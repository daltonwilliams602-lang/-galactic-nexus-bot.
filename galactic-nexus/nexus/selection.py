"""Read-only selection reports joined to the current Discord member list."""
import csv
import io
from collections import Counter
from datetime import datetime, timezone

import discord

from .blueprint import RANKS


STATUS = {
    'jedi': 'Jedi / Light Side',
    'sith': 'Sith / Dark Side',
    'unselected': 'Joined — needs /path',
    'not_joined': 'Not joined — needs /join, then /path',
    'review': 'Selection needs staff review',
    'bot': 'Bot — selection not required',
}
PAGE_SIZE = 8


def selection_rows(members, states):
    """Include unregistered members and bots, but never departed members."""
    rows = []
    for member in members:
        state = states.get(str(member.id), {})
        path = state.get('path')
        accepted = state.get('accepted', False)
        if member.bot:
            status = 'bot'
        elif not accepted:
            status = 'not_joined'
        elif not path:
            status = 'unselected'
        else:
            status = path if path in RANKS else 'review'
        rank = state.get('rank', 0)
        rank_name = (RANKS[path][rank] if path in RANKS and type(rank) is int
                     and 0 <= rank < len(RANKS[path]) else 'Force Sensitive')
        rules = ('Not applicable' if member.bot else 'Not accepted' if not accepted else
                 '18+ confirmed' if state.get('minimum_age_confirmed', 0) >= 18 else
                 'Earlier rules; 18+ confirmation not recorded')
        rows.append(dict(id=str(member.id), username=member.name, name=member.display_name,
                         status=status, side=STATUS.get(path, 'Not selected'),
                         accepted=bool(accepted), rank=rank_name, rules=rules))
    return sorted(rows, key=lambda row: (row['name'].casefold(), row['username'].casefold(), int(row['id'])))


def filter_rows(rows, selection):
    if selection == 'all':
        return rows
    if selection == 'incomplete':
        return [row for row in rows if row['status'] in {'not_joined', 'unselected', 'review'}]
    if selection == 'complete':
        return [row for row in rows if row['status'] in {'jedi', 'sith'}]
    return [row for row in rows if row['status'] == selection]


def selection_page(rows, selected, selection, page, generated_at):
    counts = Counter(row['status'] for row in rows)
    pages = max(1, (len(selected) + PAGE_SIZE - 1) // PAGE_SIZE)
    if not 1 <= page <= pages:
        raise ValueError(f'Choose a page from 1 to {pages}.')
    lines = [
        '**Galactic Nexus — Selection log**',
        f'Current members: **{len(rows) - counts["bot"]}** people + **{counts["bot"]}** bots',
        f'Jedi: **{counts["jedi"]}** | Sith: **{counts["sith"]}** | Needs /path: **{counts["unselected"]}** | Needs /join: **{counts["not_joined"]}**',
    ]
    if counts['review']:
        lines.append(f'Needs staff review: **{counts["review"]}**')
    lines.append(f'Filter: **{selection}** · {len(selected)} results · Page **{page}/{pages}** · <t:{int(generated_at)}:f>\n')
    for row in selected[(page - 1) * PAGE_SIZE:page * PAGE_SIZE]:
        name = discord.utils.escape_mentions(discord.utils.escape_markdown(' '.join(row['name'].split())[:36]))
        lines.append(f'• **{name}** (<@{row["id"]}>) — {STATUS[row["status"]]}')
    if not selected:
        lines.append('No members match this filter.')
    lines.append('\nCSV includes every matching member, plus rules-confirmation status. Use `page` for more results.')
    return '\n'.join(lines)


def csv_cell(value):
    """Prevent member-controlled names being evaluated as spreadsheet formulas."""
    text = str(value)
    if text and (text.lstrip().startswith(('=', '+', '-', '@')) or text[0] in '\t\r\n'):
        return "'" + text
    return text


def selection_csv(rows, generated_at):
    output = io.StringIO(newline='')
    writer = csv.writer(output, quoting=csv.QUOTE_ALL)
    writer.writerow(['Discord ID', 'Username', 'Server display name', 'Selected side',
                     'Selection status', 'Onboarding completed', 'Rank', 'Rules confirmation', 'Generated at (UTC)'])
    timestamp = datetime.fromtimestamp(generated_at, timezone.utc).isoformat()
    for row in rows:
        writer.writerow(["'" + row['id'], csv_cell(row['username']), csv_cell(row['name']),
                         csv_cell(row['side']), STATUS[row['status']],
                         'N/A' if row['status'] == 'bot' else 'Yes' if row['accepted'] else 'No',
                         'N/A' if row['status'] == 'bot' else row['rank'], row['rules'], timestamp])
    return output.getvalue().encode('utf-8-sig')
