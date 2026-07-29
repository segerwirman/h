import os, json, time, shutil

local_state_path = os.path.join(os.environ['LOCALAPPDATA'], 'Google', 'Chrome', 'User Data', 'Local State')
profile_dir = os.path.join(os.environ['LOCALAPPDATA'], 'Google', 'Chrome', 'User Data', 'Profile 8')

print(f"LocalState: {local_state_path}")
print(f"Profile Dir: {profile_dir}")

os.makedirs(profile_dir, exist_ok=True)
print("Ensured Profile 8 folder")

# Backup
backup_name = local_state_path + f".bak_{int(time.time())}"
shutil.copy2(local_state_path, backup_name)
print(f"Backup created: {backup_name}")

with open(local_state_path, 'r', encoding='utf-8') as f:
    data = json.load(f)

info_cache = data['profile']['info_cache']

if 'Profile 8' not in info_cache:
    print("Creating new Profile 8")
else:
    print("Profile 8 already exists, will overwrite name")

new_entry = {
    "active_time": time.time() + 10000,
    "avatar_icon": "chrome://theme/IDR_PROFILE_AVATAR_42",
    "background_apps": False,
    "default_avatar_fill_color": -14966353,
    "default_avatar_stroke_color": -12974006,
    "enterprise_label": "",
    "force_signin_profile_locked": False,
    "gaia_given_name": "",
    "gaia_id": "",
    "gaia_name": "",
    "gaia_picture_file_name": "",
    "hosted_domain": "",
    "is_consented_primary_account": False,
    "is_ephemeral": False,
    "is_glic_eligible": False,
    "is_managed": 0,
    "is_using_default_avatar": True,
    "is_using_default_name": False,
    "last_downloaded_gaia_picture_url_with_size": "",
    "managed_user_id": "",
    "metrics_bucket_index": 9,
    "name": "Jarvis chrome",
    "profile_color_seed": -14966353,
    "profile_highlight_color": -14966353,
    "shortcut_name": "Jarvis chrome",
    "signin.with_credential_provider": False,
    "user_accepted_account_management": False,
    "user_name": ""
}
# Fix color seed with valid int
new_entry["profile_color_seed"] = -14966353

info_cache["Profile 8"] = new_entry

# Ensure order
order = data['profile'].get('profiles_order', [])
if 'Profile 8' not in order:
    order.append('Profile 8')
    data['profile']['profiles_order'] = order

data['profile']['profiles_created'] = max(data['profile'].get('profiles_created', 0), 9)

metrics = data['profile'].get('metrics', {})
metrics['next_bucket_index'] = max(metrics.get('next_bucket_index', 0), 10)
data['profile']['metrics'] = metrics

with open(local_state_path, 'w', encoding='utf-8') as f:
    json.dump(data, f)

print("Local State written")

# Create Preferences file
pref_path = os.path.join(profile_dir, 'Preferences')
if not os.path.exists(pref_path):
    prefs = {
        "profile": {"name": "Jarvis chrome"},
        "browser": {"has_seen_welcome_page": True},
        "account_info": []
    }
    with open(pref_path, 'w', encoding='utf-8') as pf:
        json.dump(prefs, pf)
    print(f"Created Preferences at {pref_path}")
else:
    print("Preferences exists")

# Verify
with open(local_state_path, 'r', encoding='utf-8') as f:
    data2 = json.load(f)
print("FINAL PROFILES:", list(data2['profile']['info_cache'].keys()))
print("Profile 8 name:", data2['profile']['info_cache']['Profile 8']['name'])
print("DONE")
