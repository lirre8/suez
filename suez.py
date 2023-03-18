from datetime import datetime

import click
from rich import box, markup
from rich.console import Console
from rich.table import Table

from clnclient import ClnClient
from feepolicy import FeePolicy
from lndcliclient import LndCliClient
from lndrestclient import LndRestClient
from score import Score


def _sort_channels(c):
    return c.local_balance / (c.capacity - c.commit_fee)


def _since(ts):
    d = datetime.utcnow() - datetime.utcfromtimestamp(ts)
    return "%0.1f" % (d.total_seconds() / 86400)


def _resolve_htlc(htlc_msat):
    if htlc_msat is None:
        return "-"
    htlc_sat = htlc_msat / 1000
    htlc_sat = int(htlc_sat) if htlc_sat == int(htlc_sat) else htlc_sat
    return "{:,}".format(htlc_sat)


def _resolve_disabled(c):
    local = "y" if c.local_disabled else "n" if c.local_disabled is not None else "-"
    remote = "y" if c.remote_disabled else "n" if c.remote_disabled is not None else "-"
    res = "[bright_blue]{}[/bright_blue]|[bright_yellow]{}[/bright_yellow]"
    return res.format(local, remote)


def info_box(ln, score):
    grid = Table.grid()
    grid.add_column(style="bold")
    grid.add_column()
    grid.add_row("pubkey    : ", ln.local_pubkey)
    grid.add_row("alias     : ", ln.local_alias)
    grid.add_row("channels  : ", "%d" % len(ln.channels))
    if score is not None:
        node_score = score.get(ln.local_pubkey)
        node_score = "{:,}".format(node_score) if node_score is not None else "-"
        grid.add_row("score     : ", node_score)
    return grid


def channelcount_info_box(count, channel_type):
    grid = Table.grid()
    grid.add_column(style="bold")
    grid.add_column()
    grid.add_row("%s channels : " % channel_type, "%d" % count)
    return grid


def channel_table(
    channels,
    score,
    show_remote_fees,
    show_chan_ids,
    show_forwarding_stats,
    show_minmax_htlc,
    show_disabled,
):
    table = Table(box=box.SIMPLE)
    table.add_column("\ninbound", justify="right", style="bright_red")
    table.add_column("\nratio", justify="center")
    table.add_column("\noutbound", justify="right", style="green")
    if show_disabled:
        table.add_column("is\ndisabled", justify="right")
    if show_minmax_htlc:
        table.add_column("local\nmin_htlc\n(sat)", justify="right", style="bright_blue")
        table.add_column("local\nmax_htlc\n(sat)", justify="right", style="bright_blue")
        table.add_column(
            "remote\nmin_htlc\n(sat)", justify="right", style="bright_yellow"
        )
        table.add_column(
            "remote\nmax_htlc\n(sat)", justify="right", style="bright_yellow"
        )
    table.add_column("local\nbase_fee\n(msat)", justify="right", style="bright_blue")
    table.add_column("local\nfee_rate\n(ppm)", justify="right", style="bright_blue")
    table.add_column("remote\nbase_fee\n(msat)", justify="right", style="bright_yellow")
    table.add_column("remote\nfee_rate\n(ppm)", justify="right", style="bright_yellow")
    table.add_column("\nuptime\n(%)", justify="right")
    table.add_column("last\nforward\n(days)", justify="right")
    table.add_column("local\nfees\n(sat)", justify="right", style="bright_cyan")
    if show_forwarding_stats:
        table.add_column("\nfwd in", justify="right")
        table.add_column("\nin %", justify="right")
        table.add_column("\nfwd out", justify="right")
        table.add_column("\nout %", justify="right")
    if show_remote_fees:
        table.add_column("remote\nfees\n(sat)", justify="right", style="bright_cyan")
    if score is not None:
        table.add_column("\nscore", justify="right")
    table.add_column("\nalias", max_width=25, no_wrap=True)
    if show_chan_ids:
        table.add_column("\nchan_id")

    total_local, total_fees_local = 0, 0
    total_remote, total_fees_remote = 0, 0
    local_base_fees, local_fee_rates = [], []
    remote_base_fees, remote_fee_rates = [], []

    for c in sorted(channels, key=_sort_channels):
        send = int(round(10 * c.local_balance / (c.capacity - c.commit_fee)))
        recv = 10 - send
        bar = (
            "[bright_red]"
            + ("·" * recv)
            + "[/bright_red]"
            + "|"
            + "[green]"
            + ("·" * send)
            + "[/green]"
        )
        if c.uptime is not None and c.lifetime:
            uptime = 100 * c.uptime // c.lifetime
        else:
            uptime = "n/a"
        total_fees_local += c.local_fees_msat
        total_fees_remote += c.remote_fees
        total_local += c.local_balance
        total_remote += c.remote_balance
        if c.local_base_fee is not None:
            local_base_fees.append(c.local_base_fee)
        if c.local_fee_rate is not None:
            local_fee_rates.append(c.local_fee_rate)
        if c.remote_base_fee is not None:
            remote_base_fees.append(c.remote_base_fee)
        if c.remote_fee_rate is not None:
            remote_fee_rates.append(c.remote_fee_rate)
        columns = [
            "{:,}".format(c.remote_balance),
            bar,
            "{:,}".format(c.local_balance),
        ]
        if show_disabled:
            columns += [
                _resolve_disabled(c),
            ]
        if show_minmax_htlc:
            columns += [
                _resolve_htlc(c.local_min_htlc),
                _resolve_htlc(c.local_max_htlc),
                _resolve_htlc(c.remote_min_htlc),
                _resolve_htlc(c.remote_max_htlc),
            ]
        columns += [
            str(c.local_base_fee) if c.local_base_fee is not None else "-",
            str(c.local_fee_rate) if c.local_fee_rate is not None else "-",
            str(c.remote_base_fee) if c.remote_base_fee is not None else "-",
            str(c.remote_fee_rate) if c.remote_fee_rate is not None else "-",
            "[green]%s[/green]" % uptime
            if c.active
            else "[bright_red]%s[/bright_red]" % uptime,
            _since(c.last_forward) if c.last_forward else "never",
            "{:,}".format(round(c.local_fees_msat / 1000))
            if c.local_fees_msat
            else "-",
        ]
        if show_forwarding_stats:
            columns += [
                "{}".format(c.ins),
                "{:.0%}".format(c.ins_percent),
                "{}".format(c.outs),
                "{:.0%}".format(c.outs_percent),
            ]
        if show_remote_fees:
            columns += [
                "{:,}".format(c.remote_fees) if c.remote_fees else "-",
            ]
        if score is not None:
            s = score.get(c.remote_node_id)
            columns += [
                "{:,}".format(s) if s is not None else "-",
            ]
        alias_color = "bright_blue" if c.opener == "local" else "bright_yellow"
        alias = c.remote_alias if c.remote_alias else c.remote_node_id[:16]
        columns += [
            "[%s]%s[/%s]" % (alias_color, markup.escape(alias), alias_color),
        ]
        if show_chan_ids:
            columns += [c.chan_id]
        table.add_row(*columns)

    columns = [
        "─" * 6,
        None,
        "─" * 6,
    ]
    if show_disabled:
        columns += [
            None,
        ]
    if show_minmax_htlc:
        columns += [
            None,
            None,
            None,
            None,
        ]
    columns += [
        "─" * 4,
        "─" * 4,
        "─" * 4,
        "─" * 4,
        None,
        None,
        "─" * 6,
    ]
    if show_remote_fees:
        columns += ["─" * 6]
    table.add_row(*columns)
    columns = [
        "{:,}".format(total_remote),
        None,
        "{:,}".format(total_local),
    ]
    if show_disabled:
        columns += [
            None,
        ]
    if show_minmax_htlc:
        columns += [
            None,
            None,
            None,
            None,
        ]
    columns += [
        "{}".format(sum(local_base_fees) // len(local_base_fees)),
        "{}".format(sum(local_fee_rates) // len(local_fee_rates)),
        "{}".format(sum(remote_base_fees) // len(remote_base_fees)),
        "{}".format(sum(remote_fee_rates) // len(remote_fee_rates)),
        None,
        None,
        "{:,}".format(round(total_fees_local / 1000)),
    ]
    if show_remote_fees:
        columns += [
            "{:,}".format(total_fees_remote),
        ]
    table.add_row(*columns)
    return table


@click.command()
@click.option("--base-fee", default=0, help="Set base fee.")
@click.option("--fee-rate", default=0, help="Set fee rate.")
@click.option("--fee-spread", default=0.0, help="Fee spread.")
@click.option("--time-lock-delta", default=40, help="Set time lock delta.")
@click.option(
    "--client",
    default="lnd",
    type=click.Choice(("lnd", "c-lightning", "lnd-rest"), case_sensitive=False),
    help="Type of LN client.",
)
@click.option(
    "--client-args",
    default=[],
    multiple=True,
    help="Extra arguments to pass to client RPC.",
)
@click.option(
    "--show-remote-fees", is_flag=True, help="Show (estimate of) remote fees."
)
@click.option(
    "--show-scores", is_flag=True, help="Show node scores (from Lightning Terminal)."
)
@click.option("--show-chan-ids", is_flag=True, help="Show channel ids.")
@click.option(
    "--show-forwarding-stats",
    is_flag=True,
    help="Show forwarding counts and success percentages (CLN)",
)
@click.option("--show-minmax-htlc", is_flag=True, help="Show min and max htlc.")
@click.option("--show-disabled", is_flag=True, help="Show if channel is disabled.")
@click.option(
    "--channels",
    default="all",
    type=click.Choice(("all", "public", "private", "split"), case_sensitive=False),
    help="Which channels to select/show.",
)
def suez(
    base_fee,
    fee_rate,
    fee_spread,
    time_lock_delta,
    client,
    client_args,
    show_remote_fees,
    show_scores,
    show_chan_ids,
    show_forwarding_stats,
    show_minmax_htlc,
    show_disabled,
    channels,
):
    clients = {
        "lnd": LndCliClient,
        "c-lightning": ClnClient,
        "lnd-rest": LndRestClient,
    }

    ln = clients[client](client_args)

    score = Score() if show_scores else None

    if len(ln.channels) == 0:
        click.echo("No channels found. Exiting")
        return

    if fee_rate:
        policy = FeePolicy(base_fee, fee_rate, fee_spread, time_lock_delta)
        ln.apply_fee_policy(policy)
        ln.refresh()

    info = info_box(ln, score)

    console = Console()
    console.print()
    console.print(info)

    if channels == "split":
        public_channels = [c for c in ln.channels.values() if not c.private]
        private_channels = [c for c in ln.channels.values() if c.private]

        if len(public_channels) > 0:
            public_table = channel_table(
                public_channels,
                score,
                show_remote_fees,
                show_chan_ids,
                show_forwarding_stats,
                show_minmax_htlc,
                show_disabled,
            )
            public_info = channelcount_info_box(len(public_channels), "public")
            console.print(public_table)
            console.print(public_info)

        if len(private_channels) > 0:
            private_table = channel_table(
                private_channels,
                score,
                show_remote_fees,
                show_chan_ids,
                show_forwarding_stats,
                show_minmax_htlc,
                show_disabled,
            )
            private_info = channelcount_info_box(len(private_channels), "private")
            console.print(private_table)
            console.print(private_info)
        console.print()

    else:
        if channels == "public":
            show_channels = [c for c in ln.channels.values() if not c.private]
        elif channels == "private":
            show_channels = [c for c in ln.channels.values() if c.private]
        else:  # all
            show_channels = ln.channels.values()

        if len(show_channels) > 0:
            table = channel_table(
                show_channels,
                score,
                show_remote_fees,
                show_chan_ids,
                show_forwarding_stats,
                show_minmax_htlc,
                show_disabled,
            )
            console.print(table)
