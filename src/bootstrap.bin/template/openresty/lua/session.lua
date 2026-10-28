local cjson = require "cjson.safe"
local resty_session = require "resty.session"

local M = {}

function M.init(memcached)
  local secret = os.getenv("SESSION_SECRET")
  if not secret or secret == "" then
    error("SESSION_SECRET is not set; start OpenResty with make start")
  end
  resty_session.init({
    secret = secret,
    cookie_name = "session",
    cookie_same_site = "Lax",
    storage = "memcached",
    memcached = { host = memcached.host, port = memcached.port },
  })
end

local function deny(status, message)
  ngx.status = status
  ngx.header.content_type = "application/json"
  ngx.say(cjson.encode({ error = message }))
  return ngx.exit(status)
end

local function open_user()
  local session, _, exists = resty_session.open()
  if not exists then
    return session, nil
  end
  local id = session:get("user_id")
  if not id then
    return session, nil
  end
  return session, { id = id, email = session:get("email") }
end

-- Returns { id, email } for the current request, or nil.
function M.current()
  local _, user = open_user()
  return user
end

-- Use in access_by_lua_block. Rejects with 401 or passes X-User-Id upstream.
function M.require_session()
  ngx.req.clear_header("X-User-Id")
  local session, user = open_user()
  if not user then
    return deny(ngx.HTTP_UNAUTHORIZED, "unauthorized")
  end
  session:refresh()
  ngx.var.auth_user_id = user.id
  ngx.req.set_header("X-User-Id", user.id)
end

-- Saving issues a new session ID, so a session fixed before login is not reused.
function M.login(user)
  local session = resty_session.open()
  session:set_data({ user_id = user.id, email = user.email })
  local ok, err = session:save()
  if not ok then
    return nil, err
  end
  return true
end

function M.logout()
  return resty_session.logout()
end

return M
