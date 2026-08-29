# EduMatcher in one command

```bash
curl -fsSL https://raw.githubusercontent.com/johan162/EduMatcher/main/deployment/curl/install.sh | bash
```

Then open <http://localhost:8090>.

That starts a complete exchange — the matching engine, all the protocol
gateways, the REST API — plus four web applications, from prebuilt images.
The only requirement is **Podman or Docker**. Nothing is compiled: no Python,
no Node, no checkout of this repository.

| | |
|---|---|
| Trading terminal | <http://localhost:8090> |
| Log viewer | <http://localhost:8091> |
| Configuration builder | <http://localhost:8092> |
| Trader GUI | <http://localhost:8093> |
| REST API docs | <http://localhost:8080/docs> |

## Choosing what the exchange trades

EduMatcher ships twelve ready-made configurations, from a single order book to
thirty, each in a `basic`, `nominal` or `complex` variant. Pick one at install
time:

```bash
curl -fsSL .../install.sh | bash -s -- --config ten-nominal
```

or afterwards:

```bash
cd ~/.edumatcher
./edumatcher.sh config thirty-complex
./edumatcher.sh restart
```

The full set is `one-`, `three-`, `ten-` and `thirty-` prefixed with `basic`,
`nominal` or `complex` — `./edumatcher.sh config` lists them if you mistype one.

### Running a configuration of your own

Author one however you like — the configuration builder at
<http://localhost:8092> is the easy path, or start from a bundled example — then
point the exchange at the file:

```bash
./edumatcher.sh config ./my-market.yaml
./edumatcher.sh restart
```

The file is copied into `~/.edumatcher/config/` and deployed on every start, so
editing it and restarting is the whole edit-test loop. Switching back to a
bundled example is `./edumatcher.sh config three-basic`.

## Everyday commands

Everything lives in `~/.edumatcher` and is driven by one script:

```bash
cd ~/.edumatcher
./edumatcher.sh status              # containers, plus the exchange process table
./edumatcher.sh logs terminal-gui   # follow one service
./edumatcher.sh shell               # a shell inside the exchange container
./edumatcher.sh shell pm-opctl-cli list   # ...or one command in it
./edumatcher.sh urls                # the table above, with your ports
./edumatcher.sh mounts              # which directory is behind each container path
./edumatcher.sh stop                # stop everything; ./data is kept
./edumatcher.sh start               # bring it back
./edumatcher.sh update              # pull the newest release and restart
./edumatcher.sh update 0.20.5       # ...or pin an exact one
./edumatcher.sh uninstall           # remove containers and volumes, keep data
./edumatcher.sh uninstall --data    # remove everything
```

### Running exchange commands

The `pm-*` command line tools live inside the exchange container. `shell` puts
you there, with every command on the PATH and the data directory already set:

```bash
./edumatcher.sh shell
# then, inside:
pm-opctl-cli list          # what is running
pm-config-show             # the deployed configuration
pm-alf-console --id TRADER01
```

Pass a command to run just that one and come straight back:

```bash
./edumatcher.sh shell pm-opctl-cli list
./edumatcher.sh shell pm-log-cli --tail 20
```

The full-screen tools work too — `TERM` is forwarded, and the exit status of
whatever you ran is the exit status of `edumatcher.sh`, so it composes in
scripts.

### When a GUI shows something unexpected

The health pages report *container* paths — the log viewer says its database is
`/backend-data/log.db`, which tells you nothing about whose data that is.
`./edumatcher.sh mounts` answers both halves of that question:

```console
$ ./edumatcher.sh mounts
This install: /home/you/.edumatcher

edumatcher               ghcr.io/johan162/edumatcher:0.26.2  [running]
    /home/you/.edumatcher/data -> /data
    /home/you/.edumatcher/config -> /config

edumatcher-log-gui       ghcr.io/johan162/edumatcher-log-gui:0.26.2  [running]
    /home/you/.edumatcher/data -> /backend-data
    /var/lib/containers/volumes/edumatcher_log-gui-acks/_data -> /app/ack-data
```

A data mount that does not point into this directory is flagged `NOT this
install`, and the image name tells you where a container came from:
`ghcr.io/…` is a released install, `localhost/…` one built from a source
checkout. That combination is what identifies a container belonging to a
different EduMatcher install — `start` refuses to run alongside one, but a
stack started before that check existed can still be there.

## Installer options

```
--version X.Y.Z   Release to install (default: the latest)
--config NAME     Bundled example, or a path to your own engine_config.yaml
--dir PATH        Where to install (default: ~/.edumatcher)
--no-start        Fetch and configure, but do not start
```

Pass them through the pipe with `bash -s --`:

```bash
curl -fsSL .../install.sh | bash -s -- --version 0.20.5 --dir ~/exchange
```

## Testing this installer before a release carries it

`install.sh` fetches `compose.yaml` and `edumatcher.sh` from the release tag it
is installing, so the files and the images always come from one commit. To try
it out before such a release exists, point the fetch at a branch:

```bash
REPO_REF=main ./deployment/curl/install.sh --version 0.20.5 --dir /tmp/em-test
```

The images still come from GHCR at the version you name, so that version's
images have to be published first.

## How it fits together

All five containers share one compose project, so they share its network and
the GUIs reach the exchange at the hostname `edumatcher`. The ports published
on your machine are for *you* — `curl`, Swagger, the protocol example clients —
and are not involved in GUI-to-backend traffic.

`BIND_ADDR` in `.env` decides how far that reaches. It is `127.0.0.1`, this
machine only. **The protocol gateways have no authentication**, so anyone who
can open the socket can trade; think before setting it to `0.0.0.0` on a
network you do not control.

Two things are resolved for you at startup, because neither can be a fixed
default: the trading terminal's read-only API key is generated per
configuration, and lives on a different gateway instance than the trading one,
so `./edumatcher.sh start` reads it out of the deployed configuration and hands
it to the terminal. Everything else is plain compose — read `compose.yaml`.

## Data

Everything the exchange produces — trades, order books, audit log, the
databases — is in `~/.edumatcher/data`, on your disk, not inside a container.
It survives stop, start and update. `uninstall --data` is what deletes it.

## Building from source instead

If you want to change the code rather than run it, use
[`../docker/`](../docker/), which builds the same five images from your
checkout with `make up-all`.
