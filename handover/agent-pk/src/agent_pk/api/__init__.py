"""The HTTP surface: two channels, two routes, two different payload types.

NOT imported by `agent_pk.api`'s consumers implicitly — `app.py` needs FastAPI, and the numeric
core's test suite must keep running in an environment that does not have it. Import it
explicitly:

    from agent_pk.api.app import app
"""
