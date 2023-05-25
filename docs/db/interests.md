# interests

Describes an interest that a user might have. Interests are intended to
customize nearly every aspect of the experience - the copy that they see, the
journeys they are offered, the functionality they can use, etc. Most of these
customizations live on the frontend, since it may be as extreme as completely
swapping out views.

See also:

- [visitor_interests](./visitor_interests.md)
- [user_interests](./user_interests.md)

## Fields

- `id (integer primary key)`: Internal row identifier
- `slug (text unique not null)`: Primary stable external identifier, e.g.,
  "sleep"

## Schema

```sql
CREATE TABLE interests (
    id INTEGER PRIMARY KEY,
    slug TEXT UNIQUE NOT NULL
);
```
