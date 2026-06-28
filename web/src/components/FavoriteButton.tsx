import { useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../api'

export function FavoriteButton({
  id,
  favorite,
  className = '',
}: {
  id: string
  favorite: boolean
  className?: string
}) {
  const qc = useQueryClient()
  const mutation = useMutation({
    mutationFn: () => api.setFavorite(id, !favorite),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['sessions'] })
      qc.invalidateQueries({ queryKey: ['session', id] })
    },
  })

  return (
    <button
      onClick={(e) => {
        e.preventDefault()
        e.stopPropagation()
        mutation.mutate()
      }}
      disabled={mutation.isPending}
      title={favorite ? 'Unfavorite' : 'Favorite'}
      className={`text-base leading-none transition ${
        favorite ? 'text-amber-400' : 'text-text-faint hover:text-amber-400'
      } ${className}`}
    >
      {favorite ? '★' : '☆'}
    </button>
  )
}
