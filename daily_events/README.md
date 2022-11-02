# Daily Events

This file describes the overview of how daily events function. Besides the admin
functions, such as creating and searching, users use some endpoint to get a daily
event reference in the form of a JWT, where the sub of the JWT is the uid of the daily
event. They can use that to get the journey options available for that event, or to
join a journey via the corresponding websockets endpoint.
