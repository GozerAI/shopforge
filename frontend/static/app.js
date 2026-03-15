/* ShopForge Dashboard */
(function() {
    var authToken = sessionStorage.getItem("shopforge_token");
    var tenant = null;
    try { tenant = JSON.parse(sessionStorage.getItem("shopforge_tenant")); } catch(e) {}

    function esc(s) { var d = document.createElement("div"); d.textContent = s || ""; return d.innerHTML; }
    function showError(id, msg) { var e = document.getElementById(id); if(e){e.textContent=msg;e.classList.remove("hidden");} }
    function hideError(id) { var e = document.getElementById(id); if(e){e.textContent="";e.classList.add("hidden");} }
    function showView(id) { document.querySelectorAll(".view").forEach(function(v){v.classList.add("hidden")}); document.getElementById(id).classList.remove("hidden"); }
    function isPro() { if(!tenant) return false; var e = tenant.entitlements || []; return e.indexOf("shopforge:full") >= 0; }

    function api(path, opts) {
        opts = opts || {};
        var headers = Object.assign({"Content-Type":"application/json"}, opts.headers || {});
        if(authToken) headers["Authorization"] = "Bearer " + authToken;
        return fetch(path, Object.assign({}, opts, {headers: headers})).then(function(res) {
            if(res.status === 401) { logout(); throw new Error("Session expired"); }
            if(!res.ok) return res.json().catch(function(){return {detail:res.statusText}}).then(function(b){throw new Error(b.detail || "Request failed")});
            return res.json();
        });
    }

    function logout() { authToken=null; tenant=null; sessionStorage.removeItem("shopforge_token"); sessionStorage.removeItem("shopforge_tenant"); showView("login-view"); }

    document.getElementById("login-form").addEventListener("submit", function(e) {
        e.preventDefault(); var btn = e.target.querySelector("button"); btn.disabled = true; hideError("login-error");
        api("/api/auth/login", {method:"POST", body: JSON.stringify({email:document.getElementById("login-email").value, password:document.getElementById("login-password").value})})
        .then(function(res) { authToken=res.access_token; tenant=res.tenant||{}; sessionStorage.setItem("shopforge_token",authToken); sessionStorage.setItem("shopforge_tenant",JSON.stringify(tenant)); enterDashboard(); })
        .catch(function(err) { showError("login-error",err.message); })
        .finally(function() { btn.disabled=false; });
    });

    document.getElementById("signup-form").addEventListener("submit", function(e) {
        e.preventDefault(); var btn = e.target.querySelector("button"); btn.disabled = true; hideError("signup-error");
        api("/api/auth/register", {method:"POST", body: JSON.stringify({name:document.getElementById("signup-name").value, email:document.getElementById("signup-email").value, password:document.getElementById("signup-password").value})})
        .then(function(res) { authToken=res.access_token; tenant=res.tenant||{}; sessionStorage.setItem("shopforge_token",authToken); sessionStorage.setItem("shopforge_tenant",JSON.stringify(tenant)); enterDashboard(); })
        .catch(function(err) { showError("signup-error",err.message); })
        .finally(function() { btn.disabled=false; });
    });

    document.getElementById("show-signup").addEventListener("click", function(e){e.preventDefault();hideError("signup-error");showView("signup-view");});
    document.getElementById("show-login-from-signup").addEventListener("click", function(e){e.preventDefault();showView("login-view");});
    document.getElementById("logout-btn").addEventListener("click", logout);

    var pages = ["overview","storefronts","inventory","analytics","billing","settings"];
    function showPage(name) {
        pages.forEach(function(p){document.getElementById("page-"+p).classList.toggle("hidden",p!==name);});
        document.querySelectorAll(".nav-item").forEach(function(n){n.classList.toggle("active",n.dataset.page===name);});
        document.getElementById("page-title").textContent = name.charAt(0).toUpperCase()+name.slice(1);
        var loaders={overview:loadOverview,storefronts:loadStorefronts,inventory:loadInventory,analytics:loadAnalytics,billing:loadBilling,settings:loadSettings};
        if(loaders[name]) loaders[name]();
    }
    document.querySelectorAll(".nav-item").forEach(function(btn){btn.addEventListener("click",function(){showPage(btn.dataset.page);});});

    function enterDashboard() {
        var badge = document.getElementById("plan-badge");
        badge.innerHTML = isPro() ? '<span class="badge badge-founder">Founder Pro</span>' : '<span class="badge badge-info">Starter</span>';
        showView("dashboard-view"); showPage("overview");
    }

    function statCard(l,v){return '<div class="stat-card"><div class="stat-label">'+esc(l)+'</div><div class="stat-value">'+esc(String(v))+'</div></div>';}
    function settingRow(l,v){return '<div class="setting-row"><span class="setting-label">'+esc(l)+'</span><span class="setting-value">'+v+'</span></div>';}

    function loadOverview() {
        var el = document.getElementById("page-overview");
        Promise.all([api("/v1/stats").catch(function(){return null}), api("/v1/inventory/alerts?threshold=10").catch(function(){return []})])
        .then(function(r) {
            var stats=r[0], alerts=r[1], h='<div class="stats-grid">';
            if(stats){h+=statCard("Storefronts",stats.storefronts||0);h+=statCard("Shopify",stats.has_shopify?"Connected":"\u2014");h+=statCard("Medusa",stats.has_medusa?"Connected":"\u2014");}
            else{h+=statCard("Storefronts","0");h+=statCard("Status","No data");}
            h+="</div>";
            if(Array.isArray(alerts)&&alerts.length>0){
                h+='<h3 style="margin:1.5rem 0 .75rem">Inventory Alerts</h3>';
                alerts.slice(0,10).forEach(function(a){var lv=(a.quantity||0)===0?"error":"warning";h+='<div class="card"><span class="badge badge-'+lv+'">'+(a.quantity===0?"Out of stock":"Low stock")+'</span> <strong>'+esc(a.product_title||"Unknown")+'</strong> <span style="color:var(--text-muted)">'+a.quantity+' units</span></div>';});
            } else { h+='<div class="empty" style="margin-top:1.5rem">No inventory alerts. Connect a storefront to get started.</div>'; }
            el.innerHTML=h;
        }).catch(function(err){el.innerHTML='<div class="empty">'+esc(err.message)+'</div>';});
    }

    function loadStorefronts() {
        var el = document.getElementById("page-storefronts");
        api("/v1/storefronts").then(function(items) {
            var h="";
            if(Array.isArray(items)&&items.length>0){
                h+='<div class="table-wrap"><table><thead><tr><th>Key</th><th>Type</th><th>Status</th></tr></thead><tbody>';
                items.forEach(function(s){var t=s.shopify?"Shopify":s.medusa?"Medusa":"Unknown";h+='<tr><td><strong>'+esc(s.key||s.name||"\u2014")+'</strong></td><td><span class="badge badge-info">'+t+'</span></td><td><span class="badge badge-success">Active</span></td></tr>';});
                h+="</tbody></table></div>";
            } else { h+='<div class="empty">No storefronts connected yet.</div>'; }
            h+='<div class="connect-form"><h3>Connect Shopify Store</h3><form id="connect-shopify-form"><div class="form-row"><input type="text" id="sf-key" placeholder="Store key" required><input type="url" id="sf-url" placeholder="Store URL" required></div><div class="form-row"><input type="text" id="sf-token" placeholder="Access token" required></div><button type="submit" class="btn-primary btn-small">Connect</button></form><div id="connect-error" class="form-error hidden"></div></div>';
            el.innerHTML=h;
            document.getElementById("connect-shopify-form").addEventListener("submit",function(ev){
                ev.preventDefault();hideError("connect-error");
                api("/v1/storefronts/shopify",{method:"POST",body:JSON.stringify({key:document.getElementById("sf-key").value,store_url:document.getElementById("sf-url").value,access_token:document.getElementById("sf-token").value})})
                .then(function(){loadStorefronts();}).catch(function(err){showError("connect-error",err.message);});
            });
        }).catch(function(err){el.innerHTML='<div class="empty">'+esc(err.message)+'</div>';});
    }

    function loadInventory() {
        var el = document.getElementById("page-inventory");
        api("/v1/inventory/alerts?threshold=25").then(function(alerts) {
            if(!Array.isArray(alerts)||alerts.length===0){el.innerHTML='<div class="empty">No inventory alerts. All stock levels healthy.</div>';return;}
            var h='<div class="table-wrap"><table><thead><tr><th>Product</th><th>Variant</th><th>Qty</th><th>Status</th></tr></thead><tbody>';
            alerts.forEach(function(a){var lv=(a.quantity||0)===0?"error":"warning";h+='<tr><td>'+esc(a.product_title||"\u2014")+'</td><td>'+esc(a.variant_title||"\u2014")+'</td><td>'+a.quantity+'</td><td><span class="badge badge-'+lv+'">'+(a.quantity===0?"Out of stock":"Low stock")+'</span></td></tr>';});
            h+="</tbody></table></div>";el.innerHTML=h;
        }).catch(function(err){el.innerHTML='<div class="empty">'+esc(err.message)+'</div>';});
    }

    function loadAnalytics() {
        var el = document.getElementById("page-analytics");
        if(!isPro()){el.innerHTML='<div class="gate-notice"><h3>Analytics requires Pro</h3><p>Upgrade for pricing optimization, margin analysis, and trend enrichment.</p><br><button class="btn-primary btn-small" onclick="document.querySelector(\'[data-page=billing]\').click()">View Plans</button></div>';return;}
        api("/v1/analytics").then(function(data) {
            var h='<div class="stats-grid">';
            if(data.total_revenue!==undefined) h+=statCard("Revenue","$"+Number(data.total_revenue).toLocaleString());
            if(data.total_orders!==undefined) h+=statCard("Orders",data.total_orders);
            if(data.avg_order_value!==undefined) h+=statCard("AOV","$"+Number(data.avg_order_value).toFixed(2));
            h+="</div>";el.innerHTML=h;
        }).catch(function(err){el.innerHTML='<div class="empty">'+esc(err.message)+'</div>';});
    }

    function loadBilling() {
        var el = document.getElementById("page-billing");
        var pro = isPro();
        el.innerHTML='<div class="plan-grid">'+
            '<div class="plan-card '+(!pro?"current":"")+'"><h3>Free</h3><div class="plan-price">$0<span>/mo</span></div><ul><li>1 storefront</li><li>Inventory alerts</li><li>Basic stats</li></ul>'+(!pro?'<button class="btn-secondary" disabled>Current Plan</button>':'')+'</div>'+
            '<div class="plan-card '+(pro?"current":"")+'"><h3>Pro <span class="badge badge-founder">Founder Rate</span></h3><div class="plan-price">$19<span>/mo</span> <span class="strike">$29</span></div><ul><li>Unlimited storefronts</li><li>Analytics dashboard</li><li>Pricing optimization</li><li>Margin analysis</li><li>Trend enrichment</li><li>Executive reports</li></ul>'+
            (pro?'<button class="btn-secondary" disabled>Current Plan</button>':'<a href="https://gozerai.com/pricing" target="_blank" class="btn-primary" style="display:block;text-align:center;text-decoration:none">Upgrade to Pro</a>')+
            '<p class="plan-note">Founder pricing locks in for life.</p></div></div>';
    }

    function loadSettings() {
        var el = document.getElementById("page-settings");
        var h='<div class="settings-block"><h3>Account</h3>';
        if(tenant){h+=settingRow("Email",esc(tenant.email||"\u2014"));h+=settingRow("Tenant",esc(tenant.tenant_id||"\u2014"));h+=settingRow("Plan",esc(tenant.plan||"starter"));h+=settingRow("Status",esc(tenant.status||"active"));}
        h+="</div>";
        if(tenant&&tenant.entitlements){h+='<div class="settings-block"><h3>Entitlements</h3>';tenant.entitlements.forEach(function(e){h+=settingRow(esc(e),'<span class="badge badge-success">Active</span>');});h+="</div>";}
        h+='<div class="settings-block"><h3>Service Health</h3><div id="health-data">Loading...</div></div>';
        el.innerHTML=h;
        api("/health/detailed").then(function(d){
            var hh=settingRow("Status",'<span class="status-dot '+(d.status==="ok"?"ok":"err")+'"></span>'+esc(d.status));
            if(d.checks) Object.keys(d.checks).forEach(function(k){var v=d.checks[k];hh+=settingRow(esc(k),'<span class="status-dot '+(v.status==="ok"?"ok":"err")+'"></span>'+esc(v.status));});
            document.getElementById("health-data").innerHTML=hh;
        }).catch(function(){document.getElementById("health-data").innerHTML=settingRow("Health",'<span class="status-dot err"></span>Unavailable');});
    }

    if(authToken){api("/health").then(function(){enterDashboard();}).catch(function(){logout();});}
})();
