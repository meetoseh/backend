# Resources

This contains generic utility methods for working with resources. We try to
do as much as possible while ensuring strong type checking.

Much of this is dedicated to dealing with listing resources, since we want
to support the following type of query:


```json
{
  "filters": {
    "uid": {
      "value": "string",
      "operator": "gt"
    },
    "user_email": {
        "value": "string",
        "operator": "like"
    }
  },
  "sort": [
    {
      "key": "uid",
      "dir": "asc",
      "after": "string"
    }
  ],
  "limit": 5
}
```
