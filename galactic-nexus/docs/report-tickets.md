# Report tickets

Members use `/report reason:<what happened> member:<who is being reported>`.
The member field is optional for general concerns and appeals. The private
confirmation shows the report details; confirming creates an open ticket and
returns its ID. Staff receive the report in the private reports channel.

Staff commands:

- `/ticket summary status:open page:1`: open queue (defaults to open, page 1).
  Use status `closed` or `all` to include completed reports.
- `/ticket view ticket:<ID>`: full reason, reporter, reported member, submission
  time, status, and any saved resolution.
- `/close ticket ticket:<ID> actions_taken:<what you did and why>`: preview and
  confirm closure. Notes are required. This records the staff member and time,
  posts a closure notice in reports, and retains the original report and audit
  history. It does not issue a timeout, ban, or other moderation action.
- `/dashboard section:reports`: open tickets with reporter and reported member.

Ticket commands require current staff authorization and reply privately. A
pending closure confirmation cannot overwrite another staff member's closure.
Older reports remain accessible with their existing IDs; missing reported-member
information is shown as not specified.
