\# Deploy API



\*\*Deploy like Heroku. Pay like a VPS.\*\*



A deployment platform that gives you PaaS simplicity with VPS economics. Push code, get URL, done.



---



\## Two Ways to Deploy



| | \*\*Pioneer\*\* | \*\*Managed\*\* |

|---|-------------|-------------|

| \*\*Status\*\* | ✅ Available now | 🚧 Coming soon |

| \*\*Price\*\* | Free forever | Starting at $12/service |

| \*\*You provide\*\* | DigitalOcean + Cloudflare accounts | Just your code |

| \*\*We provide\*\* | Orchestration, UI, automation | Everything |

| \*\*Best for\*\* | Developers who want control | Teams who want simplicity |



---



\## Pioneer Program (Free Forever)



For developers who want the power of a PaaS without giving up control of their infrastructure.



\### How It Works



1\. \*\*Connect your accounts\*\* - Link your DigitalOcean and Cloudflare tokens

2\. \*\*Create a snapshot\*\* - One-click setup of a pre-configured server image (in YOUR DO account)

3\. \*\*Deploy\*\* - Push Docker images or Git repos, we handle the rest

4\. \*\*Pay only DO\*\* - Your servers, your billing, typically $6-24/month per server



\### What You Get



| Feature | Included |

|---------|----------|

| One-click deployments | ✅ |

| Real-time streaming logs | ✅ |

| One-click rollbacks | ✅ |

| Stateful services (Postgres, Redis, etc.) | ✅ |

| Auto env injection (`POSTGRES\_URL`, etc.) | ✅ |

| Automatic DNS via Cloudflare | ✅ |

| SSL via Cloudflare proxy | ✅ |

| Multi-server load balancing | ✅ |

| Architecture visualization | ✅ |

| \*\*Price\*\* | \*\*$0\*\* |



\### The Catch?



None. Pioneer users keep free access forever. You're helping us build and refine the product—that's the exchange.



When we launch the Managed tier, you'll have the option to upgrade (we handle everything) or stay on Pioneer (you keep your DO setup).



---



\## Managed Tier (Coming Soon)



For teams who want zero infrastructure headaches.



```

Your Code → Deploy API → Live App

&nbsp;          (we handle the rest)

```



\### What Changes



| Pioneer | Managed |

|---------|---------|

| You manage DO account | We manage servers |

| You see droplets | You see "services" |

| You create snapshots | Invisible, automatic |

| You pay DO directly | Simple per-service pricing |

| Your domain or subdomain | `yourapp.deployapi.app` included |



\### Planned Pricing



| Plan | Price | Includes |

|------|-------|----------|

| \*\*Starter\*\* | $12/service/month | Always-on, 1GB RAM, shared CPU |

| \*\*Pro\*\* | $24/service/month | 2GB RAM, dedicated CPU |

| \*\*Team\*\* | $99/month + services | Collaboration, audit logs, priority support |



\*No cold starts. No egress fees. No surprises.\*



\*\*Interested?\*\* \[Join the waitlist](#) to get early access and founding member pricing.



---



\## Pain Points We Solve



\### 1. 💸 \*\*PaaS Pricing That Scales Against You\*\*



| Platform | 10 Services/month |

|----------|-------------------|

| Heroku | $250-500 |

| Railway | $150-300 |

| Render | $70-200 |

| \*\*Deploy API Pioneer\*\* | \*\*$40-80\*\* (DO costs only) |

| \*\*Deploy API Managed\*\* | \*\*~$120\*\* (coming soon) |



\### 2. 🐌 \*\*Cold Starts Kill User Experience\*\*



Free tiers spin down. Your app takes 30+ seconds to wake.



\*\*Deploy API\*\*: Always-on servers. No cold starts, ever.



\### 3. 🔒 \*\*Vendor Lock-in\*\*



Proprietary buildpacks. Platform-specific magic. Pain to migrate.



\*\*Deploy API\*\*: Standard Docker containers. Take your setup anywhere.



\### 4. 🌍 \*\*Data Sovereignty\*\*



Can't choose where your data lives. Compliance nightmares.



\*\*Deploy API Pioneer\*\*: Deploy to any DO region. Your servers, your data.



\### 5. 📈 \*\*Surprise Bills\*\*



"Usage-based" pricing that explodes with traffic.



\*\*Deploy API\*\*: Predictable costs. Pioneer = just DO bills. Managed = flat per-service.



\### 6. 🏗️ \*\*Database Setup is a Pain\*\*



Managed databases cost $15-50/month each. Connecting them is manual.



\*\*Deploy API\*\*: One-click Postgres/Redis with \*\*automatic URL injection\*\*.



```python

\# Your app just works

DATABASE\_URL = os.environ\["POSTGRES\_URL"]  # Auto-populated!

```



---



\## Key Features



\### 🚀 One-Click Deployments



Deploy from Docker images, Git repos, or local archives. Real-time streaming logs:



```

📦 Pulling image myapp:latest...

✅ Image pulled

🐳 Starting container on port 8000...

🔍 Health check passed!

🌐 DNS updated: myapp.example.com

🎉 Live in 47 seconds!

```



\### 🔄 Instant Rollbacks



Every deployment tagged with unique version. One click to restore any previous state.



\### 🗄️ Stateful Services



Deploy PostgreSQL, Redis, MySQL, MongoDB with one click. Connection URLs auto-injected into your apps.



\### 🌐 Automatic DNS \& SSL



Cloudflare integration handles DNS records and SSL certificates. Zero configuration.



\### 📊 Architecture Visualization



See your entire infrastructure: services, servers, ports, health status, dependencies.



---



\## Architecture



```

┌─────────────────────────────────────────────────────────────────┐

│                        Your Browser                              │

│                     (Deploy Dashboard)                           │

└─────────────────────────────┬───────────────────────────────────┘

&nbsp;                             │

&nbsp;                             ▼

┌─────────────────────────────────────────────────────────────────┐

│                    Deploy API (Orchestration)                    │

│         Auth • Deploy Service • DNS • Billing (Managed)          │

└─────────────────────────────┬───────────────────────────────────┘

&nbsp;                             │

&nbsp;         ┌───────────────────┼───────────────────┐

&nbsp;         ▼                   ▼                   ▼

&nbsp;  ┌─────────────┐     ┌─────────────┐     ┌─────────────┐

&nbsp;  │ DigitalOcean│     │  Cloudflare │     │ Docker Hub  │

&nbsp;  │  (Servers)  │     │    (DNS)    │     │  (Images)   │

&nbsp;  └──────┬──────┘     └─────────────┘     └─────────────┘

&nbsp;         │

&nbsp;         ▼

┌─────────────────────────────────────────────────────────────────┐

│                      Your Servers                                │

│  ┌───────────────────────────────────────────────────────────┐  │

│  │  Node Agent                                                │  │

│  │  • Pulls \& runs containers                                 │  │

│  │  • Manages nginx reverse proxy                             │  │

│  │  • Handles SSL via Cloudflare                              │  │

│  │  • Reports health status                                   │  │

│  └───────────────────────────────────────────────────────────┘  │

│  ┌───────────┐  ┌───────────┐  ┌───────────┐  ┌───────────┐    │

│  │  Your App │  │  Postgres │  │   Redis   │  │  Worker   │    │

│  └───────────┘  └───────────┘  └───────────┘  └───────────┘    │

└─────────────────────────────────────────────────────────────────┘

```



\*\*Pioneer\*\*: You own the DigitalOcean account, we orchestrate deployments.



\*\*Managed\*\*: We own the infrastructure, you just deploy code.



---



\## Comparison



| Feature | Deploy API | Heroku | Railway | Render | Coolify |

|---------|------------|--------|---------|--------|---------|

| \*\*No cold starts\*\* | ✅ | ⚠️ Paid only | ⚠️ Paid only | ✅ | ✅ |

| \*\*Predictable pricing\*\* | ✅ | ❌ | ⚠️ | ⚠️ | ✅ |

| \*\*Use your own servers\*\* | ✅ Pioneer | ❌ | ❌ | ❌ | ✅ |

| \*\*Fully managed option\*\* | ✅ Coming | ✅ | ✅ | ✅ | ❌ |

| \*\*Auto env injection\*\* | ✅ | ❌ | ❌ | ❌ | ❌ |

| \*\*One-click databases\*\* | ✅ | ✅ ($$$) | ✅ | ✅ ($$$) | ✅ |

| \*\*Instant rollbacks\*\* | ✅ | ✅ | ✅ | ✅ | ✅ |

| \*\*No self-hosting required\*\* | ✅ | ✅ | ✅ | ✅ | ❌ |

| \*\*Data sovereignty\*\* | ✅ | ❌ | ❌ | ❌ | ✅ |



\### When to Use What



| Situation | Best Choice |

|-----------|-------------|

| Want control + low cost | \*\*Deploy API Pioneer\*\* |

| Want zero ops | \*\*Deploy API Managed\*\* (soon) / Railway |

| Need self-hosted | Coolify |

| Have budget, need enterprise support | Heroku |

| Serverless functions | Vercel |



---



\## Quick Start (Pioneer)



\### Prerequisites



\- DigitalOcean account (\[get $200 free credit](https://digitalocean.com))

\- Cloudflare account (free tier works)

\- A domain pointed to Cloudflare



\### Steps



1\. \*\*Sign up\*\* at \[deploy-api.dev](https://deploy-api.dev)

2\. \*\*Connect\*\* your DO and Cloudflare API tokens

3\. \*\*Create snapshot\*\* - guided setup, takes ~10 minutes

4\. \*\*Deploy\*\* - enter Docker image or Git URL, click deploy

5\. \*\*Done\*\* - your app is live with SSL



---



\## FAQ



\*\*Q: Why is Pioneer free?\*\*  

A: Early users help us refine the product. You get free tooling, we get feedback. When Managed launches, you keep free access forever.



\*\*Q: What's the catch?\*\*  

A: You manage your own DigitalOcean account and billing. That's the tradeoff for free orchestration.



\*\*Q: Will Pioneer stay free?\*\*  

A: Yes. Pioneer users are grandfathered forever. We may cap features (e.g., max 10 services) eventually, but existing usage stays free.



\*\*Q: How is this different from Coolify?\*\*  

A: Coolify requires self-hosting the control plane. Deploy API is a managed service—you don't run anything except your actual apps.



\*\*Q: Can I switch from Pioneer to Managed later?\*\*  

A: Yes. We'll offer migration tools when Managed launches. Your apps move seamlessly.



\*\*Q: What about security?\*\*  

A: Servers use DO firewalls + SSH keys. The node agent authenticates via HMAC. Your tokens are encrypted at rest. All traffic is HTTPS via Cloudflare.



\*\*Q: Do you have access to my servers?\*\*  

A: Only via the node agent API (HMAC-authenticated). We don't store SSH keys. You have full root access.



---



\## Roadmap



\- \[x] Core deployment engine

\- \[x] Stateful services with auto-injection

\- \[x] Cloudflare DNS automation

\- \[x] One-click rollbacks

\- \[ ] \*\*Managed tier\*\* (Q2 2025)

\- \[ ] GitHub Actions integration

\- \[ ] Auto-scaling

\- \[ ] Multi-cloud (AWS, Hetzner)

\- \[ ] Built-in CI/CD

\- \[ ] Log aggregation dashboard



---



\## Get Started



\*\*Pioneer (Free)\*\*: \[Sign up now](https://deploy-api.dev) → Connect accounts → Deploy in minutes



\*\*Managed (Coming Soon)\*\*: \[Join waitlist](https://deploy-api.dev/waitlist) → Get notified + founding member pricing



---



\*Built for developers who want deployment simplicity without vendor lock-in.\*

