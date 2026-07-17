# Contributing

Contributions are welcome under the repository's MIT license. Before the first
public release, coordinate larger changes through issues or review notes.

For code or contract changes:

1. describe the methodological or reliability problem;
2. add a regression test that demonstrates it;
3. preserve the consumer-neutral dependency direction;
4. run `python3 -m ruff check 90_UTILITIES`;
5. run `python3 90_UTILITIES/tests/run_tests.py`;
6. update the changelog and relevant contract when behavior changes.

Never add real interviews, participant identifiers, credentials, access tokens
or consumer-specific governance records as fixtures.
