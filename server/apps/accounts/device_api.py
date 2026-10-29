from datetime import timedelta
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.views.decorators.csrf import csrf_protect
from rest_framework import permissions
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from django.contrib.auth.hashers import check_password
from .device_auth import (PIN_TRIES, COOKIE, COOKIE_PATH, state, valid, cookie_credential,
                          issue_credential, access_token, set_cookie)
from .models import DeviceSession, RefreshCredential, SessionAudit
from .protected_pages import pin_for


class ActivityThrottle(UserRateThrottle):
    rate='6/minute'
    scope='activity'


def payload(request, device, include_token=False):
    from .api import identity
    request.user=device.user
    request._request.device_session=device
    data=identity(device.user,request)
    data['session']=state(device)
    if include_token:
        data.update(access_token=access_token(device),access_expires_in=settings.JWT_ACCESS_SECONDS)
    return data


def locked_response(device):
    return Response({'detail':'Your workspace is locked. Enter your password.', 'code':'session_locked',
        'id':device.user_id,'username':device.user.username,'authenticated':True,'session':state(device)},status=423)


def lost_reply(device, credential):
    """Whether a spent credential is the one renewed last and what it was renewed into was never used: the browser
    just missed the reply. Any other spent credential coming back is a copy, and ends the session."""
    later=RefreshCredential.objects.filter(session=device,created_at__gt=credential.created_at)
    return later.exists() and not later.filter(consumed_at__isnull=False).exists()


@api_view(['POST'])
@permission_classes([permissions.AllowAny])
@csrf_protect
@transaction.atomic
def refresh(request):
    credential=cookie_credential(request)
    if not credential:
        return Response({'detail':'Please sign in again.','code':'session_expired'},status=401)
    device=DeviceSession.objects.select_for_update().select_related('user').get(pk=credential.session_id)
    credential=RefreshCredential.objects.get(pk=credential.pk)
    if not valid(device):
        return Response({'detail':'Please sign in again.','code':'session_expired'},status=401)
    if credential.consumed_at:
        # Concurrent duplicate: reject without returning a credential or token.
        # A later replay revokes the entire family. No spent credential is accepted.
        if (timezone.now()-credential.consumed_at).total_seconds() < 3:
            return Response({'detail':'Another tab refreshed. Retry with the current cookie.','code':'refresh_conflict'},status=409)
        if not lost_reply(device, credential):
            device.revoked_at=timezone.now();device.save(update_fields=['revoked_at'])
            SessionAudit.objects.create(session=device,event='REFRESH_REUSE_REVOKED')
            return Response({'detail':'Please sign in again.','code':'session_expired'},status=401)
        # The last renewal's reply never reached the browser (the connection dropped or the computer slept), so it
        # still holds the credential before it. The unused one issued then is retired and the renewal goes ahead.
        RefreshCredential.objects.filter(session=device,consumed_at=None).update(consumed_at=timezone.now())
        SessionAudit.objects.create(session=device,event='REFRESH_LOST_REPLY')
        raw=issue_credential(device)
        if state(device)['locked']:
            return set_cookie(locked_response(device),raw,device)
        return set_cookie(Response(payload(request,device,True)),raw,device)
    if state(device)['locked']:
        if not device.locked_at:
            device.locked_at=timezone.now();device.save(update_fields=['locked_at'])
        return locked_response(device)
    credential.consumed_at=timezone.now();credential.save(update_fields=['consumed_at'])
    raw=issue_credential(device)
    # Refresh rotates credentials; it never counts as user activity.
    SessionAudit.objects.create(session=device,event='REFRESH')
    return set_cookie(Response(payload(request,device,True)),raw,device)


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
@throttle_classes([ActivityThrottle])
@transaction.atomic
def activity(request):
    device=DeviceSession.objects.select_for_update().select_related('user').get(pk=request.auth.pk)
    if not valid(device):
        return Response({'detail':'Please sign in again.'},status=401)
    if state(device)['locked']:
        return locked_response(device)
    if (timezone.now()-device.last_user_activity_at).total_seconds() >= 15:
        device.last_user_activity_at=timezone.now();device.save(update_fields=['last_user_activity_at'])
        SessionAudit.objects.create(session=device,event='ACTIVITY')
    return Response({'session':state(device)})


@api_view(['POST'])
@permission_classes([permissions.AllowAny])
@csrf_protect
@transaction.atomic
def lock(request):
    credential=cookie_credential(request)
    if not credential or credential.consumed_at or not valid(credential.session):
        return Response({'detail':'Please sign in again.'},status=401)
    device=DeviceSession.objects.select_for_update().select_related('user').get(pk=credential.session_id)
    credential.refresh_from_db()
    if credential.consumed_at or not valid(device):
        return Response({'detail':'Session changed. Please try again.','code':'refresh_conflict'},status=409)
    device.locked_at=timezone.now();device.version+=1;device.save(update_fields=['locked_at','version'])
    SessionAudit.objects.create(session=device,event='LOCK')
    return Response({'session':state(device)})


@api_view(['POST'])
@permission_classes([permissions.AllowAny])
@csrf_protect
@transaction.atomic
def unlock(request):
    credential=cookie_credential(request)
    if not credential or credential.consumed_at:
        return Response({'detail':'Your session ended. Sign in again.','code':'session_expired'},status=401)
    device=DeviceSession.objects.select_for_update().select_related('user').get(pk=credential.session_id)
    credential.refresh_from_db()
    if credential.consumed_at:
        return Response({'detail':'Session changed. Please try again.','code':'refresh_conflict'},status=409)
    if not valid(device):
        return Response({'detail':'Your session ended. Sign in again.','code':'session_expired'},status=401)
    now=timezone.now()
    if device.unlock_blocked_until and now < device.unlock_blocked_until:
        return Response({'detail':'Too many attempts. Wait a minute and try again.'},status=429)
    pin=request.data.get('pin')
    if pin is not None:
        # A PIN opens only a lock the person made themselves, and does not lengthen the session: that needs the password.
        if not state(device)['pin_length']:
            return Response({'detail':'Enter your password to unlock.','code':'password_required','session':state(device)},status=400)
        if not isinstance(pin,str) or not check_password(pin, pin_for(device.user, '').digest):
            device.failed_unlocks+=1
            device.save(update_fields=['failed_unlocks'])
            SessionAudit.objects.create(session=device,event='UNLOCK_FAILED')
            left=max(0,PIN_TRIES-device.failed_unlocks)
            detail=f'Wrong PIN. {left} {"try" if left == 1 else "tries"} left.' if left else 'Wrong PIN too many times. Enter your password to unlock.'
            return Response({'detail':detail,'code':'wrong_pin','session':state(device)},status=400)
    else:
        password=request.data.get('password','')
        if not isinstance(password,str) or not device.user.check_password(password):
            device.failed_unlocks+=1
            if device.failed_unlocks >= 5:
                device.unlock_blocked_until=now+timedelta(minutes=1)
            device.save(update_fields=['failed_unlocks','unlock_blocked_until'])
            SessionAudit.objects.create(session=device,event='UNLOCK_FAILED')
            return Response({'detail':'Incorrect password. Please try again.'},status=400)
        # The password was just checked, as at sign-in, so the session starts its full life again.
        device.expires_at=now+timedelta(seconds=settings.DEVICE_ABSOLUTE_SECONDS)
    device.locked_at=None;device.last_user_activity_at=now;device.version+=1
    device.failed_unlocks=0;device.unlock_blocked_until=None
    device.save(update_fields=['locked_at','last_user_activity_at','version','expires_at','failed_unlocks','unlock_blocked_until'])
    RefreshCredential.objects.filter(session=device,consumed_at=None).update(consumed_at=now)
    raw=issue_credential(device)
    SessionAudit.objects.create(session=device,event='UNLOCK_PIN' if pin is not None else 'UNLOCK')
    return set_cookie(Response(payload(request,device,True)),raw,device)


@api_view(['POST'])
@permission_classes([permissions.AllowAny])
@csrf_protect
@transaction.atomic
def logout(request):
    credential=cookie_credential(request)
    if credential:
        device=DeviceSession.objects.select_for_update().get(pk=credential.session_id)
        device.revoked_at=timezone.now();device.save(update_fields=['revoked_at'])
        SessionAudit.objects.create(session=device,event='LOGOUT')
    response=Response(status=204)
    response.delete_cookie(COOKIE,path=COOKIE_PATH,samesite='Strict')
    return response
