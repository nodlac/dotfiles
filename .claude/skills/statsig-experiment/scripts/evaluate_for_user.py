# Django shell against staging:  python manage.py shell < statsig-diagnose.py
from apps.account.models.user import User
from apps.common.services.statsig import StatsigService, pm_store_evaluate

EMAIL = 'cpreece@vidangel.com'  # <- the account you're testing with
user = User.objects.get(email=EMAIL)

store = StatsigService.get_parameter_store(user, 'content_features')
print('store resolved:', store is not None)

if store is not None:
    # Sentinel default: comes back only if the KEY isn't in the store at all.
    sentinel = pm_store_evaluate(store, 'service_link_warning_variant', '__MISSING__')
    print('with sentinel default:', repr(sentinel))

    # Known-good key in the same store, as a control.
    print('markwatched_enabled  :', repr(pm_store_evaluate(store, 'markwatched_enabled', False)))

    # What the app actually asks for.
    print('with empty default   :', repr(pm_store_evaluate(store, 'service_link_warning_variant', '')))

# Does the experiment itself allocate this user?
exp = StatsigService.get_experiment(user, 'web_service_link_warning')
print('experiment object:', exp)

su = StatsigService.user_from_user(user=user)
print('statsig user_id:', su.user_id)
print('staff:', su.custom.get('staff'), '| beta:', su.custom.get('beta_user'))
