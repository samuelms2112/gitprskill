'use client';

import { Trash2 } from 'lucide-react';
import { useState } from 'react';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { ErrorState } from '@/components/ui/feedback';
import { Select } from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import { useMembers, useRemoveMember, useUpdateMemberRole } from '@/features/members/queries';
import { useAuth } from '@/features/auth/auth-context';
import { errorMessage } from '@/lib/api/error-message';
import type { Member, MemberRoleValue } from '@/lib/api/members';
import { formatDateTime } from '@/lib/format';

const ROLE_LABELS: Record<MemberRoleValue, string> = {
  OWNER: 'Dono',
  DEVELOPER: 'Desenvolvedor',
  VIEWER: 'Leitor',
};

/** Gestão de usuários de uma empresa: papel de cada membro e remoção. Visível só para OWNER. */
export function MembersCard({ tenantSlug, tenantName }: { tenantSlug: string; tenantName: string }) {
  const { user } = useAuth();
  const members = useMembers(tenantSlug, true);
  const updateRole = useUpdateMemberRole(tenantSlug);
  const removeMember = useRemoveMember(tenantSlug);
  const [pendingRemoval, setPendingRemoval] = useState<number | null>(null);

  const actionError = updateRole.error ?? removeMember.error;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Usuários de {tenantName}</CardTitle>
        <CardDescription>
          Novos membros entram pelo login com o GitHub, quando pertencem à organização. Aqui você ajusta o
          papel de cada um e remove quem não deve mais ter acesso. A empresa sempre mantém ao menos um dono.
        </CardDescription>
      </CardHeader>

      <CardContent className="space-y-4">
        {members.isPending && <Skeleton className="h-40" />}

        {members.isError && (
          <ErrorState message={errorMessage(members.error)} onRetry={() => void members.refetch()} />
        )}

        {actionError && (
          <p role="alert" className="text-sm text-red-300">
            {errorMessage(actionError)}
          </p>
        )}

        {members.data && (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-left text-muted-foreground">
                <tr>
                  <th className="py-2 pr-4 font-medium">Usuário</th>
                  <th className="py-2 pr-4 font-medium">Papel</th>
                  <th className="py-2 pr-4 font-medium">Entrou em</th>
                  <th className="py-2 font-medium">
                    <span className="sr-only">Ações</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {members.data.map((member) => (
                  <MemberRow
                    key={member.user_id}
                    member={member}
                    isSelf={member.login === user?.login}
                    confirming={pendingRemoval === member.user_id}
                    busy={updateRole.isPending || removeMember.isPending}
                    onRoleChange={(role) => updateRole.mutate({ userId: member.user_id, role })}
                    onAskRemove={() => setPendingRemoval(member.user_id)}
                    onCancelRemove={() => setPendingRemoval(null)}
                    onConfirmRemove={() =>
                      removeMember.mutate(member.user_id, { onSettled: () => setPendingRemoval(null) })
                    }
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function MemberRow({
  member,
  isSelf,
  confirming,
  busy,
  onRoleChange,
  onAskRemove,
  onCancelRemove,
  onConfirmRemove,
}: {
  member: Member;
  isSelf: boolean;
  confirming: boolean;
  busy: boolean;
  onRoleChange: (role: MemberRoleValue) => void;
  onAskRemove: () => void;
  onCancelRemove: () => void;
  onConfirmRemove: () => void;
}) {
  return (
    <tr className="border-t border-border">
      <td className="py-3 pr-4">
        <div className="flex items-center gap-2">
          {member.avatar_url && (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={member.avatar_url} alt="" className="size-6 rounded-full" />
          )}
          <span className="font-medium">{member.login}</span>
          {isSelf && <span className="text-xs text-muted-foreground">(você)</span>}
        </div>
      </td>
      <td className="py-3 pr-4">
        <Select
          aria-label={`Papel de ${member.login}`}
          value={member.role}
          disabled={busy}
          onChange={(event) => onRoleChange(event.target.value as MemberRoleValue)}
          className="h-8 w-44 text-xs"
        >
          {(Object.keys(ROLE_LABELS) as MemberRoleValue[]).map((role) => (
            <option key={role} value={role}>
              {ROLE_LABELS[role]}
            </option>
          ))}
        </Select>
      </td>
      <td className="py-3 pr-4 text-muted-foreground">{formatDateTime(member.joined_at)}</td>
      <td className="py-3 text-right">
        {confirming ? (
          <div className="flex justify-end gap-2">
            <Button size="sm" variant="ghost" onClick={onCancelRemove} disabled={busy}>
              Cancelar
            </Button>
            <Button size="sm" variant="destructive" onClick={onConfirmRemove} disabled={busy}>
              Confirmar remoção
            </Button>
          </div>
        ) : (
          <Button
            size="sm"
            variant="ghost"
            onClick={onAskRemove}
            disabled={busy}
            aria-label={`Remover ${member.login}`}
          >
            <Trash2 aria-hidden />
            <span className="sr-only sm:not-sr-only">Remover</span>
          </Button>
        )}
      </td>
    </tr>
  );
}
