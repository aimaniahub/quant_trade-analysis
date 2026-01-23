# 🤖 OptionGreek Agentic AI Integration (MCP)

OptionGreek now supports the **Model Context Protocol (MCP)**. This allows you to connect AI assistants like **Claude Desktop** or **Cursor** directly to your trading engine to perform real-time analysis and portfolio management using natural language.

---

## 🛠️ Configuration for AI Agents

To enable AI intelligence, add the following configuration to your AI tool:

### For Cursor
1. Go to **Settings > Cursor Settings > Features > MCP**.
2. Add a new MCP Server:
   - **Name**: `OptionGreek`
   - **Type**: `command`
   - **Command**: `python c:/Users/prash/OneDrive/Desktop/sumanth files/optionchain/backend/mcp_launcher.py` (Create this file if using local stdio)
   - *OR* use **HTTP**: `http://localhost:8000/api/v1/mcp/call`

### For Claude Desktop
Add this to your `claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "option-greek": {
      "command": "python",
      "args": ["c:/Users/prash/OneDrive/Desktop/sumanth files/optionchain/backend/mcp_launcher.py"]
    }
  }
}
```

---

## 🧰 Available AI Tools

Once connected, your AI assistant will have access to:

| Tool | Description |
|------|-------------|
| `get_option_chain_analysis` | Detailed analysis of premiums, greeks, and anomalies. |
| `get_portfolio_summary` | Insights into funds, holdings, and net positions. |
| `place_trading_order` | Ability to execute trades via natural language. |

---

## 💬 Example AI Prompts

- *"Analyze the NIFTY option chain and find any premium imbalances in the ATM strikes."*
- *"What is my current total exposure in Bank Nifty, and how much margin is available?"*
- *"Prepare a sell order for 50 qty of NSE:SBIN-EQ at market price if the RSI crosses 70."* (Requires agentic logic)

> [!WARNING]
> While the AI can help analyze and suggest trades, always verify orders before execution. The engine provides "guardrails," but final trading decisions are yours.
