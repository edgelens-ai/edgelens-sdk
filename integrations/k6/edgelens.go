// Package edgelens is a k6 extension for the EdgeLens Edge AI Device
// Farm. Build a custom k6 binary:
//
//	xk6 build --with github.com/edgelens-ai/edgelens-sdk/integrations/k6
//
// Then in your script:
//
//	import edgelens from "k6/x/edgelens";
//
//	// Files must be opened at init scope (a k6 rule).
//	const model = open("./models/face.cvimodel", "b");
//
//	// One client per VU, at init scope, so setup(), the default function
//	// and teardown() all reach the same API with the same key.
//	const client = edgelens.connect({ apiKey: __ENV.EDGELENS_API_KEY });
//
//	export function setup() {
//	    const session = client.createSession({
//	        deviceType: "recamera-2002",
//	        os: "stock-os",
//	    });
//	    session.waitReady();
//	    session.device.deploy({ model: { name: "face.cvimodel", data: model } });
//	    session.device.inference.start();
//	    return { sessionId: session.id };
//	}
//
//	export default function (data) {
//	    const stats = client.resume(data.sessionId).device.inference.stats();
//	    // Stats are emitted as the inference_fps + inference_latency_ms
//	    // metrics — wire them into thresholds.
//	}
//
//	export function teardown(data) {
//	    client.resume(data.sessionId).release();
//	}
package edgelens

import (
	"errors"

	"go.k6.io/k6/js/modules"
)

func init() {
	modules.Register("k6/x/edgelens", New())
}

// RootModule is the global module instance — created once at extension
// load. State is per-VU and lives on Module instances.
type RootModule struct{}

// New returns a fresh root module.
func New() *RootModule { return &RootModule{} }

// NewModuleInstance is called once per VU.
func (*RootModule) NewModuleInstance(vu modules.VU) modules.Instance {
	return &Module{
		vu:      vu,
		metrics: registerMetrics(vu),
	}
}

// Module is the per-VU module instance exposed to the JS runtime.
type Module struct {
	vu      modules.VU
	metrics *edgelensMetrics
}

// Exports tells k6 what symbols live on `k6/x/edgelens`.
func (m *Module) Exports() modules.Exports {
	return modules.Exports{
		Default: m,
	}
}

// Connect returns a new client. The key is required: a client without
// one would send every call, release included, unauthenticated.
//
//	const client = edgelens.connect({ apiKey: "...", baseUrl: "..." });
func (m *Module) Connect(opts ConnectOptions) (*Client, error) {
	if opts.APIKey == "" {
		return nil, errors.New("edgelens.connect: apiKey is required (set EDGELENS_API_KEY)")
	}
	baseURL := opts.BaseURL
	if baseURL == "" {
		baseURL = "https://api.edgelens.ai"
	}
	return &Client{
		apiKey:  opts.APIKey,
		baseURL: baseURL,
		module:  m,
	}, nil
}

// ConnectOptions is what JS passes to edgelens.connect().
type ConnectOptions struct {
	APIKey  string `js:"apiKey"`
	BaseURL string `js:"baseUrl"`
}
