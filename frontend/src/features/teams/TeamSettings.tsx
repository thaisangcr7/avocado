/**
 * Team administration: who is in the team, at what role, and who is invited.
 *
 * Controls are shown according to the caller's own standing, which the server
 * reports as `your_role`. Hiding a control the server would refuse is a
 * courtesy, not a security boundary — every action here is authorised again on
 * the server, and this component assumes nothing.
 */

import { useState } from 'react'

import { ApiError } from '@/api/client'
import type { Member, Role } from '@/api/types'
import { ROLE_LABEL, ROLE_RANK, roleAtLeast } from '@/api/types'
import { Badge, Button, Card, EmptyState, ErrorNotice, Input, Spinner } from '@/components/ui/primitives'
import {
  useCreateInvitation,
  useInvitations,
  useRemoveMember,
  useRevokeInvitation,
  useSetMemberRole,
  useTeam,
  useTeamMembers,
} from '@/hooks/queries'
import { cn, formatRelativeTime } from '@/lib/utils'
import { useAuthStore } from '@/stores/auth'

export function TeamSettings({ teamId, onClose }: { teamId: string; onClose: () => void }) {
  const { data: team, isLoading } = useTeam(teamId)
  const { data: members } = useTeamMembers(teamId)
  const currentUser = useAuthStore((state) => state.user)

  const canAdminister = team ? roleAtLeast(team.your_role, 'team_admin') : false
  // Only an admin may list invitations, so asking as a member would 403.
  const { data: invitations } = useInvitations(teamId, canAdminister)

  if (isLoading || !team) {
    return (
      <div className="flex h-full items-center justify-center">
        <Spinner className="size-5 text-ink-muted" />
      </div>
    )
  }

  return (
    <div className="flex h-full flex-col overflow-y-auto">
      <header className="flex items-start justify-between gap-4 border-b border-border-subtle px-6 py-4">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <h2 className="truncate text-lg font-semibold text-ink">{team.name}</h2>
            <Badge tone="accent">{ROLE_LABEL[team.your_role]}</Badge>
          </div>
          <p className="mt-0.5 text-sm text-ink-muted">
            {team.member_count} member{team.member_count === 1 ? '' : 's'} ·{' '}
            {team.workspace_count} workspace{team.workspace_count === 1 ? '' : 's'}
          </p>
        </div>
        <Button variant="ghost" onClick={onClose}>
          Close
        </Button>
      </header>

      <div className="mx-auto w-full max-w-3xl space-y-6 px-6 py-6">
        {canAdminister && <InviteForm teamId={teamId} actorRole={team.your_role} />}

        <section>
          <h3 className="mb-2 text-sm font-semibold text-ink">Members</h3>
          <Card className="divide-y divide-border-subtle">
            {members?.map((member) => (
              <MemberRow
                key={member.user_id}
                teamId={teamId}
                member={member}
                actorRole={team.your_role}
                isSelf={member.user_id === currentUser?.id}
              />
            ))}
          </Card>
        </section>

        {canAdminister && (
          <section>
            <h3 className="mb-2 text-sm font-semibold text-ink">Invitations</h3>
            {(invitations?.length ?? 0) === 0 ? (
              <EmptyState
                title="No invitations"
                description="Invite someone by email to add them to this team."
              />
            ) : (
              <Card className="divide-y divide-border-subtle">
                {invitations!.map((invitation) => (
                  <InvitationRow
                    key={invitation.id}
                    teamId={teamId}
                    invitation={invitation}
                  />
                ))}
              </Card>
            )}
          </section>
        )}
      </div>
    </div>
  )
}

function InviteForm({ teamId, actorRole }: { teamId: string; actorRole: Role }) {
  const createInvitation = useCreateInvitation(teamId)
  const [email, setEmail] = useState('')
  const [role, setRole] = useState<Role>('member')
  const [error, setError] = useState<string | null>(null)
  const [issued, setIssued] = useState<{ url: string; email: string } | null>(null)
  const [copied, setCopied] = useState(false)

  // Nobody may invite above their own role; offering the option would only
  // produce a refusal.
  const grantableRoles = (Object.keys(ROLE_RANK) as Role[])
    .filter((candidate) => ROLE_RANK[candidate] <= ROLE_RANK[actorRole])
    .sort((a, b) => ROLE_RANK[b] - ROLE_RANK[a])

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault()
    setError(null)
    setIssued(null)
    try {
      const result = await createInvitation.mutateAsync({ email: email.trim(), role })
      setIssued({ url: result.accept_url, email: result.invitation.email })
      setEmail('')
    } catch (caught) {
      setError(
        caught instanceof ApiError ? caught.message : 'The invitation could not be created.',
      )
    }
  }

  return (
    <Card className="p-4">
      <h3 className="mb-3 text-sm font-semibold text-ink">Invite someone</h3>

      <form onSubmit={handleSubmit} className="flex flex-wrap items-end gap-2">
        <label className="min-w-48 flex-1">
          <span className="mb-1.5 block text-xs font-medium text-ink-muted">Email</span>
          <Input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="colleague@company.com"
            required
          />
        </label>

        <label>
          <span className="mb-1.5 block text-xs font-medium text-ink-muted">Role</span>
          <select
            value={role}
            onChange={(e) => setRole(e.target.value as Role)}
            className="h-10 rounded-lg border border-border-subtle bg-surface px-2 text-sm text-ink"
          >
            {grantableRoles.map((candidate) => (
              <option key={candidate} value={candidate}>
                {ROLE_LABEL[candidate]}
              </option>
            ))}
          </select>
        </label>

        <Button type="submit" loading={createInvitation.isPending} disabled={!email.trim()}>
          Send invite
        </Button>
      </form>

      {error && (
        <div className="mt-3">
          <ErrorNotice message={error} />
        </div>
      )}

      {issued && (
        <div className="mt-3 rounded-lg border border-accent/30 bg-accent-soft p-3">
          <p className="text-sm font-medium text-ink">
            Invitation link for {issued.email}
          </p>
          {/* Shown once and never again: only a hash is stored server-side, so
              there is no way to retrieve this link later. */}
          <p className="mt-0.5 text-xs text-ink-muted">
            Copy it now — it is shown once and cannot be recovered.
          </p>
          <div className="mt-2 flex gap-2">
            <input
              readOnly
              value={issued.url}
              onFocus={(e) => e.target.select()}
              className="min-w-0 flex-1 rounded-lg border border-border-subtle bg-surface px-2 py-1.5 font-mono text-xs text-ink"
            />
            <Button
              type="button"
              size="sm"
              variant="secondary"
              onClick={() => {
                void navigator.clipboard?.writeText(issued.url)
                setCopied(true)
                setTimeout(() => setCopied(false), 2000)
              }}
            >
              {copied ? 'Copied' : 'Copy'}
            </Button>
          </div>
        </div>
      )}
    </Card>
  )
}

function MemberRow({
  teamId,
  member,
  actorRole,
  isSelf,
}: {
  teamId: string
  member: Member
  actorRole: Role
  isSelf: boolean
}) {
  const setRole = useSetMemberRole(teamId)
  const removeMember = useRemoveMember(teamId)
  const [error, setError] = useState<string | null>(null)

  const canAdminister = roleAtLeast(actorRole, 'team_admin')
  const grantableRoles = (Object.keys(ROLE_RANK) as Role[])
    .filter((candidate) => ROLE_RANK[candidate] <= ROLE_RANK[actorRole])
    .sort((a, b) => ROLE_RANK[b] - ROLE_RANK[a])

  async function run(action: Promise<unknown>) {
    setError(null)
    try {
      await action
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'That did not work.')
    }
  }

  return (
    <div className="px-4 py-3">
      <div className="flex flex-wrap items-center gap-3">
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium text-ink">
            {member.full_name || member.email}
            {isSelf && <span className="ml-1.5 text-xs text-ink-muted">(you)</span>}
          </p>
          <p className="truncate text-xs text-ink-muted">
            {member.email} · joined {formatRelativeTime(member.joined_at)}
          </p>
        </div>

        {canAdminister && !isSelf ? (
          <select
            value={member.role}
            onChange={(e) =>
              void run(setRole.mutateAsync({ userId: member.user_id, role: e.target.value as Role }))
            }
            className="h-8 rounded-lg border border-border-subtle bg-surface px-2 text-xs text-ink"
            aria-label={`Role for ${member.email}`}
          >
            {grantableRoles.map((candidate) => (
              <option key={candidate} value={candidate}>
                {ROLE_LABEL[candidate]}
              </option>
            ))}
          </select>
        ) : (
          <Badge tone={member.role === 'org_admin' ? 'accent' : 'neutral'}>
            {ROLE_LABEL[member.role]}
          </Badge>
        )}

        {(canAdminister || isSelf) && (
          <Button
            size="sm"
            variant="ghost"
            onClick={() => void run(removeMember.mutateAsync(member.user_id))}
          >
            {isSelf ? 'Leave' : 'Remove'}
          </Button>
        )}
      </div>

      {error && (
        <p role="alert" className="mt-1.5 text-xs text-danger">
          {error}
        </p>
      )}
    </div>
  )
}

function InvitationRow({
  teamId,
  invitation,
}: {
  teamId: string
  invitation: { id: string; email: string; role: Role; status: string; expires_at: string }
}) {
  const revoke = useRevokeInvitation(teamId)
  const isPending = invitation.status === 'pending'

  return (
    <div className="flex flex-wrap items-center gap-3 px-4 py-3">
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm text-ink">{invitation.email}</p>
        <p className="text-xs text-ink-muted">
          {ROLE_LABEL[invitation.role]}
          {isPending && ` · expires ${formatRelativeTime(invitation.expires_at)}`}
        </p>
      </div>

      <Badge
        tone={
          invitation.status === 'accepted'
            ? 'success'
            : invitation.status === 'pending'
              ? 'warning'
              : 'neutral'
        }
      >
        {invitation.status}
      </Badge>

      {isPending && (
        <Button
          size="sm"
          variant="ghost"
          loading={revoke.isPending}
          onClick={() => revoke.mutate(invitation.id)}
          className={cn(revoke.isPending && 'pointer-events-none')}
        >
          Revoke
        </Button>
      )}
    </div>
  )
}
