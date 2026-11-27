"""Start the DR Runbook Agent on http://localhost:8088.

Without model access the drill, approvals, rollback and reports all work.
With a key in .env, the two Agent Framework agents and the Foundry /responses endpoint switch on.
"""
import argparse
import logging
import os

import uvicorn
from dotenv import load_dotenv

from drill import agents
from drill.coordinator import ROOT, Coordinator
from drill.web import create_app, create_hosted_server


def main():
    parser = argparse.ArgumentParser(description="DR Runbook Agent (simulation only)")
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT", "8088")))
    args = parser.parse_args()
    load_dotenv(ROOT / ".env")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    coord = Coordinator()
    config = agents.provider()
    if config:
        app = create_hosted_server(coord, args.port)
        mode = f"{config['name']} {config['model']}; Foundry Responses endpoint at /responses"
    else:
        app = create_app(coord, args.port)
        mode = "no model configured (deterministic mode)"
    print(f"DR Runbook Agent (SIMULATION ONLY) - http://localhost:{args.port} - {mode}")
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")  # localhost only, on purpose


if __name__ == "__main__":
    main()
