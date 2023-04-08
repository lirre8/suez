import requests


class TerminalWeb:
    def __init__(self, local_pubkey, show_scores, show_good_peers):
        self.local_pubkey = local_pubkey
        self.show_scores = show_scores
        self.show_good_peers = show_good_peers
        if show_scores or show_good_peers:
            try:
                r = requests.get(
                    f"https://terminal.lightning.engineering/_next/data/a47c92e1/{local_pubkey}.json?pubkey={local_pubkey}",
                    headers={"referer": "https://terminal.lightning.engineering/"},
                )
                j = r.json()
                self.local_node = j["pageProps"]["node"]
            except:
                self.local_node = None

    def is_good_inbound_peer(self, remote_pubkey):
        if not self.local_node or "goodInboundPeers" not in self.local_node:
            return False
        return remote_pubkey in self.local_node["goodInboundPeers"]

    def is_good_outbound_peer(self, remote_pubkey):
        if not self.local_node or "goodOutboundPeers" not in self.local_node:
            return False
        return remote_pubkey in self.local_node["goodOutboundPeers"]

    def get_score(self, pubkey):
        if pubkey != self.local_pubkey or not self.local_node:
            # FIXME Remote node's score needs a separate API request
            return None
        return self.local_node.get("score")
