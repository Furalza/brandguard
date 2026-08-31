# Demo: generalization to an unseen sector

These files show the system running on a brand from a sector it was not built
around (crypto, a high-value phishing target), with records that appear in no
training or evaluation set. The point is to demonstrate that the cascade
generalizes rather than memorizing the banking and logistics cases.

Run it:

```bash
python run.py --profile data/demo/kripto_profile.json \
              --records data/demo/kripto_records.json --pretty
```

The seven records cover: the official wallet, a fresh-publisher clone requesting
SMS/contacts, a Cyrillic homoglyph, a legitimate price tracker, an airdrop scam
(the realistic crypto attack: "connect your wallet, enter your seed phrase"), an
unrelated crypto-themed game, and a repackaged mirror. Adding the crypto sector
required one line in `_SECTOR_EXPECTED` (scored_signals.py); everything else is
sector-agnostic.
