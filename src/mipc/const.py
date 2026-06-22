BASE_HOST = "https://www.mipcm.com:7443"
PRIME = "791658605174853458830696113306796803"
ROOT_NUM = "5"
CAM_TIMEOUT = 30000  # ms — controls when the signaling session is cleared and re-authed
MAX_REQUEST_TRY = 3

PATHS = {
    "HOSTS":       "/cmipcgw/cmipcgw_get_req.js",
    "CREATE_SESSION": "/mmq_create.js",
    "KEY":         "/cacs_dh_req.js",
    "LOGIN":       "/cacs_login_req.js",
    "DEVICES":     "/ccm_devs_get.js",
    "PLAY":        "/ccm_play.js",
    "STILL_IMAGE": "/ccm_pic_get.jpg",
    "CONTROL":     "/ccm_ptz_ctl.js",
}

TIMEOUT = 10  # seconds for HTTP requests
