# Python Agent Server

A FastAPI-based agentic orchestration server with provider-agnostic LLM support, parallel subagents, enterprise security, skills, memory, and soul systems.

## Features

- **Provider-Agnostic**: Supports Azure OpenAI, AWS Bedrock, Google Gemini, OpenAI, Ollama, and local GGUF models
- **Parallel Subagents**: Concurrent execution of up to 4 subagents by default
- **Enterprise Security**: Enforced security policies with read-only constitution
- **Skills System**: Specialized capabilities and domain knowledge
- **Memory & Soul**: Persistent memory and personality systems
- **Web Interface**: Built-in frontend with real-time WebSocket communication
- **Extensible Architecture**: Modular design for easy customization

## Quick Start

### Prerequisites

- Python 3.8+
- Git

### Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/yourusername/agent_server.git
   cd agent_server
   ```

2. Create a virtual environment:
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```

3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

4. Configure providers in `config.json` (see Configuration section)

5. Start the server:
   ```bash
   python main.py
   ```

The server will be available at `http://localhost:8000`

## Configuration

Edit `config.json` to configure LLM providers and server settings:

```json
{
  "providers": {
    "priority": ["azure_openai", "aws_bedrock", "google", "openai", "ollama", "local"],
    "azure_openai": {
      "enabled": true,
      "endpoint": "https://your-resource.cognitiveservices.azure.com/",
      "api_key": "your-api-key",
      "api_version": "2024-12-01-preview",
      "model": "gpt-4",
      "auth_header": false
    }
  },
  "agents": {
    "orchestrator": {
      "provider": "azure_openai",
      "model": "gpt-4"
    },
    "subagents": {
      "provider": "azure_openai",
      "model": "gpt-4",
      "max_concurrent": 4
    }
  },
  "server": {
    "host": "0.0.0.0",
    "port": 8000,
    "reload": false
  }
}
```

### Security Setup

The server requires a `storage/security/Security.md` file containing organizational policies. This file must be read-only at the OS level:

```bash
chmod 444 storage/security/Security.md
```

## Architecture

### Core Components

- **Orchestrator**: Main agent that coordinates subagents and manages conversations
- **Subagents**: Specialized agents that can run in parallel
- **Providers**: Abstraction layer for different LLM services
- **Skills**: Domain-specific capabilities and workflows
- **Memory**: Persistent storage for facts, user profiles, and project context
- **Soul**: Personality and boot configuration system

### API Endpoints

- `GET /` - Web interface
- `POST /api/chat` - Send messages to the orchestrator
- `WebSocket /ws` - Real-time communication

### Directory Structure

```
agent_server/
├── agent/              # Core agent logic
│   ├── orchestrator.py # Main orchestrator
│   ├── subagent.py     # Subagent implementation
│   └── session.py      # Session management
├── api/                # FastAPI routes and WebSocket
├── providers/          # LLM provider implementations
├── skills/             # Specialized capabilities
├── storage/            # Persistent data
│   ├── memory/         # Facts and context
│   ├── sessions/       # Chat sessions
│   ├── security/       # Security policies
│   └── soul/           # Personality system
├── tools/              # Utility tools
├── frontend/           # Web interface
├── config.json         # Configuration
└── main.py            # Server entry point
```

## Usage

### Web Interface

Access the built-in web interface at `http://localhost:8000` for a chat-based interaction with the agent system.

### API Usage

```python
import requests

response = requests.post("http://localhost:8000/api/chat", 
    json={"message": "Hello, agent!"})
print(response.json())
```

### WebSocket

```javascript
const ws = new WebSocket('ws://localhost:8000/ws');
ws.onmessage = (event) => {
    console.log('Received:', event.data);
};
ws.send(JSON.stringify({message: 'Hello!'}));
```

## Development

### Adding New Providers

1. Create a new provider class in `providers/`
2. Implement the base provider interface
3. Add configuration to `config.json`
4. Update provider priority list

### Adding Skills

1. Create skill definition in `skills/definitions/`
2. Implement skill logic
3. Register in `skills/registry.py`

### Testing

```bash
# Run with auto-reload
python main.py --reload
```

## Security

- API keys are stored in configuration files (consider using environment variables)
- Security policies are enforced at startup
- All provider communications use secure protocols
- Sensitive files should be added to `.gitignore`

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request

## License

[Add your license here]

## Support

For issues and questions, please open a GitHub issue or contact the maintainers.