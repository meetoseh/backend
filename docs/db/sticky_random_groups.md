# sticky_random_groups

Used primarily within flows or flow screens for a form of A/B testing. Associates a name
to a 256-bit random number.

To determine if a user is in a group, only 2 pieces of information are used:

- The users `sub`, which includes a 128-bit random number
- The group number, which is a 256-bit random number

We shuffle this to a single 256-bit number using `HMAC-SHA256(key=group_number, msg=sub)`
Then, we generate single 64-bit random number via ChaCha20. Finally, we take the
least significant bit.

The chacha20 step might be unnecessary, but CSPRNGs are designed to have each
individual bit appear 50/50, which was not the point of HMAC-SHA256 (though,
arguably, is a necessary consequence of its other requirements).

```python
import hmac
import randomgen
import secrets

# this is the form you would receive them from the database
user_sub = f'oseh_u_{secrets.token_urlsafe(16)}'
group_number_hex = secrets.token_hex(32)

print(f"User sub: {user_sub}")
print(f"Cohort number (hex): {group_number_hex}")

group_number = bytes.fromhex(group_number_hex)
shuffled_together_bytes = hmac.digest(group_number, user_sub.encode('utf-8'), 'sha256')
shuffled_together_number = int.from_bytes(shuffled_together_bytes, 'big')
gen = randomgen.ChaCha(key=shuffled_together_number)
bit = gen.random_raw() & 1

print(f"In group: {bit}")
```

SEE ALSO: [opt_in_groups](opt_in_groups.md)

## Fields

- `id (integer primary key)`: internal row identifier
- `uid (text unique not null)`: primary stable external row identifier. Uses
  the [uid prefix](../uid_prefixes.md) `srg`. This value should not be changed
  for a row.
- `name (text not null)`: the name of the group. This value may be changed for
  a row, and is unique (case insensitively). Generally, the uid identifies the group
  number but the name identifies the semantic purpose of the group. Thus, it may be
  reasonable to swap a group out by changing the name and creating a new group with
  the old name. Be sure to clear caches when doing this (see `lib.sticky_random_groups`)
- `group_number_hex (text unique not null)`: the 256-bit random number associated with the group,
  in hex
- `created_at (real not null)`: the time the group was created

## Schema

```sql
CREATE TABLE sticky_random_groups (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    group_number_hex TEXT UNIQUE NOT NULL,
    created_at REAL NOT NULL
)

/* Uniqueness, search */
CREATE UNIQUE INDEX sticky_random_groups_name_idx ON sticky_random_groups (name COLLATE NOCASE);
```
