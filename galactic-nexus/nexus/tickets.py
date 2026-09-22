"""Private report formatting, including records created before ticket tracking."""
import discord


def ticket_rows(store, status='open'):
    records = [(rid, r) for rid, r in store.all('report').items()
               if status == 'all' or r.get('status', 'open') == status]
    records.sort(key=lambda item: (item[1].get('status', 'open') != 'open', -item[1].get('at', 0), item[0]))
    return [f"`{rid}` • {r.get('status', 'open').upper()} • Reporter: <@{r['member']}> • "
            + (f"Reported: <@{r['reported_member']}>" if r.get('reported_member') else 'Reported: not specified')
            + '\n' + discord.utils.escape_markdown(r['reason'].replace('\n', ' ')[:100])
            for rid, r in records]


def ticket_embed(rid, r):
    embed = discord.Embed(title=f"Ticket {rid} • {r.get('status', 'open').upper()}", colour=0x3498DB)
    embed.add_field(name='Reporter', value=f"<@{r['member']}>")
    embed.add_field(name='Reported member', value=f"<@{r['reported_member']}>" if r.get('reported_member') else 'Not specified / general concern')
    embed.add_field(name='Submitted', value=f"<t:{int(r['at'])}:F>", inline=False)
    reason = discord.utils.escape_markdown(r['reason'])
    for index in range(0, len(reason), 1000):
        embed.add_field(name='Reason' if index == 0 else 'Reason (continued)', value=reason[index:index+1000], inline=False)
    if r.get('status') == 'closed':
        embed.add_field(name='Closed by', value=f"<@{r['closed_by']}>" if r.get('closed_by') else 'Not recorded')
        embed.add_field(name='Closed at', value=f"<t:{int(r['closed_at'])}:F>" if r.get('closed_at') else 'Not recorded')
        notes = discord.utils.escape_markdown(r.get('actions_taken', 'Not recorded'))
        for index in range(0, len(notes), 1000):
            embed.add_field(name='Actions taken' if index == 0 else 'Actions taken (continued)', value=notes[index:index+1000], inline=False)
    embed.set_footer(text='Private staff record • /close ticket records resolution; it does not apply moderation actions.')
    return embed
