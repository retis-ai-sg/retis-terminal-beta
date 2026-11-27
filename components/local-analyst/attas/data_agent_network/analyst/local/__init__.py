"""Local Analyst: the Analyst Data Source as a Retis MAS Manager component on the person's own computer.

It scores each recent news window of a few tickers with the analysts the person chooses (any LLM they can use, on
this computer or on the site, side by side) and keeps the results in the AssetStorage they choose. It fetches nothing
and keeps nothing itself: every news read, model call and save is a data request the person's Terminal answers
(phemacast.core.data_requests). Alvin, 2026-11-23.
"""
